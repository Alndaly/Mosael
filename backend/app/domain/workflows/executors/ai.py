"""AI 文本类节点:经自动化执行面做单次补全(不产生子 job、不开放智能体工具)。"""

from __future__ import annotations

import json
from typing import Any

from jsonschema import SchemaError, ValidationError, validate as validate_json_schema
from sqlalchemy.orm import Session

from app.db.models import Workflow
from app.core.usage_scope import workspace_scope
from app.domain.ai_chat import AiChatError, chat, target_for
from app.domain.usage import billable
from app.domain.providers import require_connection
from app.domain.workflows import WorkflowDomainError
from app.domain.jobs import current_actor
from app.domain.workflows.executors import register

LLM_TIMEOUT_SECONDS = 120

# 供应商偶发瞬断(Server disconnected / 连接或读超时 / 429 限流 / 5xx 过载)是常态,让整条工作流
# 一次就挂太脆。重试与退避统一在 domain/ai_retry 的传输层做,**所有 AI 出站调用共用**;
# 这里只保留「读设置」这一步,因为工作流执行器手上正好有 db 会话。
DEFAULT_MAX_RETRIES = 3
MAX_RETRIES_CAP = 10


def configured_max_retries(db: Session) -> int:
    """读取用户设置的「供应商瞬断最大重试次数」;缺省 3,夹在 0..10。"""
    from app.db.models import AiRuntimeConfig

    row = db.get(AiRuntimeConfig, "default")
    value = row.max_retries if row is not None else DEFAULT_MAX_RETRIES
    return max(0, min(int(value), MAX_RETRIES_CAP))

# 生成风格预设 → temperature(替代让用户填裸数值)。默认均衡。
_LLM_PRESET_TEMPS = {"precise": 0.1, "balanced": 0.4, "creative": 0.9}


def _float_config(config: dict[str, Any], key: str, *, min_value: float | None = None, max_value: float | None = None) -> float | None:
    raw = config.get(key)
    if raw in (None, ""):
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise WorkflowDomainError("wfErr_mustBeNumber", params={"field": key}) from exc
    if min_value is not None and value < min_value:
        raise WorkflowDomainError("wfErr_belowMin", params={"field": key, "min": f"{min_value:g}"})
    if max_value is not None and value > max_value:
        raise WorkflowDomainError("wfErr_aboveMax", params={"field": key, "max": f"{max_value:g}"})
    return value


def _int_config(config: dict[str, Any], key: str, *, min_value: int | None = None) -> int | None:
    raw = config.get(key)
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise WorkflowDomainError("wfErr_mustBeInteger", params={"field": key}) from exc
    if min_value is not None and value < min_value:
        raise WorkflowDomainError("wfErr_belowMin", params={"field": key, "min": min_value})
    return value


def _bool_config(config: dict[str, Any], key: str, default: bool) -> bool:
    raw = config.get(key)
    if raw in (None, ""):
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {"0", "false", "no", "off", "否"}


def _stop_sequences(value: Any) -> list[str] | None:
    if value in (None, ""):
        return None
    if isinstance(value, list):
        items = [str(item).strip() for item in value if str(item).strip()]
    else:
        items = [line.strip() for line in str(value).splitlines() if line.strip()]
    return items or None


def _response_format(config: dict[str, Any]) -> dict[str, Any] | None:
    mode = str(config.get("response_format") or "text")
    if mode == "text":
        return None
    if mode == "json_object":
        return {"type": "json_object"}
    if mode != "json_schema":
        raise WorkflowDomainError("wfErr_responseFormat")
    schema = config.get("json_schema")
    if not isinstance(schema, dict) or not schema:
        raise WorkflowDomainError("wfErr_schemaEmpty")
    name = str(config.get("json_schema_name") or schema.get("title") or "workflow_output").strip() or "workflow_output"
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": schema,
            "strict": _bool_config(config, "json_schema_strict", True),
        },
    }


def _parse_json_response(text: str) -> Any:
    """Parse one JSON value even when a text-only model wraps it in prose.

    Providers that reject ``response_format`` are retried in plain-text mode by
    the shared chat gateway. Those models commonly return a Markdown fence or a
    short explanation around an otherwise valid value. ``raw_decode`` keeps the
    fallback structural (and safe for nested JSON) without trying to repair a
    truncated or malformed answer.
    """
    try:
        return json.loads(text)
    except json.JSONDecodeError as strict_error:
        decoder = json.JSONDecoder()
        for index, character in enumerate(text):
            if character not in "[{":
                continue
            try:
                value, _end = decoder.raw_decode(text, index)
            except json.JSONDecodeError:
                continue
            return value
        raise strict_error


def _request_payload(config: dict[str, Any], model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    payload: dict[str, Any] = {"model": model, "messages": messages}
    temperature = _float_config(config, "temperature", min_value=0, max_value=2)
    if temperature is None:
        temperature = _LLM_PRESET_TEMPS.get(str(config.get("preset") or "balanced"), 0.4)
    payload["temperature"] = temperature

    numeric_fields = {
        "top_p": (0.0, 1.0),
        "frequency_penalty": (-2.0, 2.0),
        "presence_penalty": (-2.0, 2.0),
    }
    for key, (min_value, max_value) in numeric_fields.items():
        value = _float_config(config, key, min_value=min_value, max_value=max_value)
        if value is not None:
            payload[key] = value
    max_tokens = _int_config(config, "max_tokens", min_value=1)
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens
    seed = _int_config(config, "seed")
    if seed is not None:
        payload["seed"] = seed
    stop = _stop_sequences(config.get("stop"))
    if stop is not None:
        payload["stop"] = stop
    response_format = _response_format(config)
    if response_format is not None:
        payload["response_format"] = response_format
    return payload


@register("llm")
def llm(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    profile = require_connection(db, config.get("profile_id"), user_id=current_actor(db), error=WorkflowDomainError)
    messages: list[dict[str, Any]] = []
    if config.get("system"):
        messages.append({"role": "system", "content": str(config["system"])})
    prompt = str(config.get("prompt", ""))
    # 空提示词是最常见的一类 400(prompt 切了「引用」却没绑上游、或上游给了空):提前拦下,给准信。
    if not prompt.strip():
        raise WorkflowDomainError("wfErr_llmPromptEmpty")
    messages.append({"role": "user", "content": prompt})
    try:
        target = target_for(db, profile, model=str(config.get("model") or ""), surface="automation")
        payload = _request_payload(config, target.model, messages)
        allow_response_format_fallback = "response_format" in payload
        with billable(
            db,
            capability="chat",
            operation="workflow_llm",
            workspace_id=workflow.workspace_id,
            source_type="workflow",
            source_id=workflow.id,
        ) as call:
            raw_text = chat(
                target,
                messages,
                temperature=float(payload.pop("temperature", 0.4)),
                timeout=LLM_TIMEOUT_SECONDS,
                extra=payload,
                max_retries=configured_max_retries(db),
                call=call,
                label="调用 LLM",
                allow_response_format_fallback=allow_response_format_fallback,
            )
            text = raw_text.strip()
    except AiChatError as exc:
        raise WorkflowDomainError(str(exc)) from exc
    result: dict[str, Any] = {"text": text}
    if str(config.get("response_format") or "text") in {"json_object", "json_schema"}:
        try:
            result["json"] = _parse_json_response(text)
        except json.JSONDecodeError as exc:
            raise WorkflowDomainError(
                "wfErr_llmNotJson",
                details={
                    "kind": "llm_json_response",
                    "model": target.model,
                    "response_format": str(config.get("response_format")),
                    "raw_response": raw_text,
                    "parse_error": str(exc),
                },
            ) from exc
        if str(config.get("response_format")) == "json_schema":
            try:
                validate_json_schema(instance=result["json"], schema=config.get("json_schema"))
            except SchemaError as exc:
                raise WorkflowDomainError("wfErr_schemaInvalid", params={"reason": exc.message}) from exc
            except ValidationError as exc:
                raise WorkflowDomainError(
                    "wfErr_jsonSchemaMismatch",
                    params={"reason": exc.message},
                    details={
                        "kind": "llm_json_response",
                        "model": target.model,
                        "response_format": "json_schema",
                        "raw_response": raw_text,
                        "schema_error": exc.message,
                    },
                ) from exc
    return result


@register("translate_lines")
def translate_lines(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """整轨一次翻完。

    **收什么都行:一列字符串,或者一列带 `text` 的段落。** 上游最常见的是逐字稿的 segments
    (每段带 start/end/text),而把整个段落对象交给翻译引擎就是把一坨 JSON 送去翻译 ——
    此前的逐句循环靠模板里写 `{{loop.item.text}}` 绕开这件事,那是把节点的职责推给了调用方。

    逐句循环也能得到同样的结果,但那是 N 次**串行**节点调用、每次一个新连接;免费端点按 IP
    限流,串起来正好踩在它的节流上(真机上第 1/31 次就 429)。这里走 translate_many:
    8 路并发、共用一条会重试的连接。

    **顺序即对齐**:第 i 条译文配第 i 段的时间码,所以空段落也要占住自己的位置 ——
    translate_many 对空串返回空串,不压缩列表。
    """
    from app.domain.translate import translate_many

    raw = config.get("texts")
    items = raw if isinstance(raw, list) else []
    texts = [
        str(item.get("text", "")) if isinstance(item, dict) else str(item if item is not None else "")
        for item in items
    ]
    if not texts:
        return {"texts": [], "count": 0}
    with workspace_scope(getattr(workflow, "workspace_id", "") or ""):
        translated = translate_many(
            db,
            texts,
            str(config.get("target_lang") or "en"),
            user_id=current_actor(db),
            engine=str(config.get("engine") or "google").lower(),
            profile_id=str(config.get("profile_id") or "") or None,
            model=str(config.get("model") or ""),
        )
    return {"texts": translated, "count": len(translated)}


@register("translate")
def translate(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.translate import translate as translate_text

    text = str(config.get("text", ""))
    if not text.strip():
        return {"text": ""}
    # 工作流跑在后台线程,没有 HTTP 请求把工作区绑进上下文 —— 显式圈一下,AI 翻译的用量才有归属。
    # workflow 可能为 None(单元测试直接调节点);那时没有归属可绑,记账会跳过并 warning。
    with workspace_scope(getattr(workflow, "workspace_id", "") or ""):
        translated = translate_text(
            db,
            text,
            str(config.get("target_lang") or "en"),
            user_id=current_actor(db),
            engine=str(config.get("engine") or "google").lower(),
            profile_id=str(config.get("profile_id") or "") or None,
            model=str(config.get("model") or ""),
        )
    return {"text": translated}
