"""AI 文本类节点:经自动化执行面做单次补全(不产生子 job、不开放智能体工具)。"""

from __future__ import annotations

import json
from typing import Any

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
        raise WorkflowDomainError(f"{key} 必须是数字") from exc
    if min_value is not None and value < min_value:
        raise WorkflowDomainError(f"{key} 不能小于 {min_value:g}")
    if max_value is not None and value > max_value:
        raise WorkflowDomainError(f"{key} 不能大于 {max_value:g}")
    return value


def _int_config(config: dict[str, Any], key: str, *, min_value: int | None = None) -> int | None:
    raw = config.get(key)
    if raw in (None, ""):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise WorkflowDomainError(f"{key} 必须是整数") from exc
    if min_value is not None and value < min_value:
        raise WorkflowDomainError(f"{key} 不能小于 {min_value}")
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
        raise WorkflowDomainError("response_format 只能是 text/json_object/json_schema")
    schema = config.get("json_schema")
    if not isinstance(schema, dict) or not schema:
        raise WorkflowDomainError("JSON Schema 不能为空")
    name = str(config.get("json_schema_name") or schema.get("title") or "workflow_output").strip() or "workflow_output"
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "schema": schema,
            "strict": _bool_config(config, "json_schema_strict", True),
        },
    }


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
        raise WorkflowDomainError("LLM 节点的提示词为空:请填写提示词,或把「引用」的上游接好、确认其有输出。")
    messages.append({"role": "user", "content": prompt})
    try:
        target = target_for(db, profile, model=str(config.get("model") or ""), surface="automation")
        payload = _request_payload(config, target.model, messages)
        with billable(
            db,
            capability="chat",
            operation="workflow_llm",
            workspace_id=workflow.workspace_id,
            source_type="workflow",
            source_id=workflow.id,
        ) as call:
            text = chat(
                target,
                messages,
                temperature=float(payload.pop("temperature", 0.4)),
                timeout=LLM_TIMEOUT_SECONDS,
                extra=payload,
                max_retries=configured_max_retries(db),
                call=call,
                label="调用 LLM",
            ).strip()
    except AiChatError as exc:
        raise WorkflowDomainError(str(exc)) from exc
    result: dict[str, Any] = {"text": text}
    if str(config.get("response_format") or "text") in {"json_object", "json_schema"}:
        try:
            result["json"] = json.loads(text)
        except json.JSONDecodeError as exc:
            raise WorkflowDomainError("LLM 未返回合法 JSON") from exc
    return result


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
        )
    return {"text": translated}
