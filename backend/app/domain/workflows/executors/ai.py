"""AI 文本类节点:直连供应商 API(不产生子 job)。"""

from __future__ import annotations

import json
import random
import time
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.db.models import Workflow
from app.domain.providers import require_profile
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import register

LLM_TIMEOUT_SECONDS = 120

# 供应商偶发瞬断(Server disconnected / 连接或读超时 / 429 限流 / 5xx 过载)是常态,让整条工作流
# 一次就挂太脆。对这类**可重试**错误做几次指数退避重试;4xx(除 429)是请求本身的问题,重试无意义。
# 「最大重试次数」用户可在设置页调整(见 AiRuntimeConfig / configured_max_retries),缺省 3。
DEFAULT_MAX_RETRIES = 3
MAX_RETRIES_CAP = 10
_LLM_RETRY_BASE_SECONDS = 1.5


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


def _is_retryable_status(status: int) -> bool:
    """429(限流)与 5xx(过载/网关)是瞬时状态,值得重试;4xx 是请求本身的问题,重试无益。"""
    return status == 429 or 500 <= status < 600


def _post_with_retry(
    base_url: str, api_key: str, payload: dict[str, Any], model: str, max_retries: int
) -> httpx.Response:
    """带指数退避重试的 chat/completions 调用:网络瞬断 / 429 / 5xx 重试,4xx 立即失败。
    max_retries 为**重试**次数(不含首次),故总尝试 = max_retries + 1。"""
    attempts = max(1, max_retries + 1)
    for attempt in range(attempts):
        last = attempt == attempts - 1
        try:
            response = httpx.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
                timeout=LLM_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            if last or not _is_retryable_status(exc.response.status_code):
                raise WorkflowDomainError(_provider_error(exc.response, model)) from exc
        except httpx.RequestError as exc:
            if last:
                suffix = f",已重试 {max_retries} 次仍失败" if max_retries > 0 else ""
                raise WorkflowDomainError(f"调用 LLM 失败(网络/连接{suffix}):{exc}") from exc
        # 退避后重试:指数增长 + 少量抖动,封顶 8s,避开与其它节点同时重击供应商。
        time.sleep(min(_LLM_RETRY_BASE_SECONDS * 2**attempt, 8.0) + random.uniform(0, 0.4))
    raise WorkflowDomainError("调用 LLM 失败:重试耗尽")  # 不可达(末次必抛),仅为类型收敛兜底


def _provider_error(response: httpx.Response, model: str) -> str:
    """把供应商的 4xx/5xx 响应体提炼成人看得懂的一行——否则只剩个裸状态码,查不出根因。"""
    detail = response.text.strip()
    try:
        body = response.json()
    except (ValueError, json.JSONDecodeError):
        body = None
    if isinstance(body, dict):
        err = body.get("error")
        if isinstance(err, dict) and err.get("message"):
            detail = str(err["message"])
        elif isinstance(err, str) and err:
            detail = err
        elif body.get("message"):
            detail = str(body["message"])
    detail = " ".join(detail.split())[:500] or "(无错误详情)"
    return f"LLM 供应商返回 {response.status_code}(模型 {model}):{detail}"


@register("llm")
def llm(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    profile = require_profile(db, config.get("profile_id"), error=WorkflowDomainError)
    messages: list[dict[str, Any]] = []
    if config.get("system"):
        messages.append({"role": "system", "content": str(config["system"])})
    prompt = str(config.get("prompt", ""))
    # 空提示词是最常见的一类 400(prompt 切了「引用」却没绑上游、或上游给了空):提前拦下,给准信。
    if not prompt.strip():
        raise WorkflowDomainError("LLM 节点的提示词为空:请填写提示词,或把「引用」的上游接好、确认其有输出。")
    messages.append({"role": "user", "content": prompt})
    base_url = profile.base_url.rstrip("/")
    model = str(config.get("model") or profile.default_model)
    response = _post_with_retry(
        base_url, profile.api_key, _request_payload(config, model, messages), model, configured_max_retries(db)
    )
    text = str(response.json()["choices"][0]["message"]["content"]).strip()
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
    return {
        "text": translate_text(
            db,
            text,
            str(config.get("target_lang") or "en"),
            engine=str(config.get("engine") or "google").lower(),
            profile_id=str(config.get("profile_id") or "") or None,
        )
    }
