"""上游 HTTP 失败 → 一条带文案 key 的 GenerationAdapterError。只加工别人抛出的 httpx 异常,自己不发请求。"""

from __future__ import annotations

from typing import Any

import httpx

from app.ai.providers.contracts.failures import UPSTREAM_ERROR_KEYS, http_status_category
from app.core.http_retry import is_retryable_status
from app.ai.providers.contracts.generation import GenerationAdapterError, sanitize_adapter_error

#: 失败的类别和归类表住在契约里(宿主也照它说话,见 contracts/failures);这里照旧导出,适配器从这儿拿。
__all__ = [
    "PollAnswerUnreadable",
    "UPSTREAM_ERROR_KEYS",
    "adapter_http_error",
    "categorized_http_error",
    "http_error_detail",
    "http_status_category",
    "transient_poll_failure",
    "upstream_error",
]


def adapter_http_error(vendor: str, exc: httpx.HTTPError, credential: str | None) -> GenerationAdapterError:
    """Surface provider HTTP failures with the response body when available.

    httpx's default message links to MDN but omits the provider's JSON error, which is the
    part users need to fix a model name, unsupported size, or missing capability.

    返回的是**一条带 key 的错误**,不是一句拼好的话:「{vendor} 请求失败:…」这半句要跟着读的人
    的语言走,后面那段上游原文(已脱敏)原样放进 `detail`。
    """
    return GenerationAdapterError("providerErr_requestFailed", vendor=vendor, detail=http_error_detail(exc, credential))


def upstream_error(vendor: str, category: str | None, detail: Any) -> GenerationAdapterError:
    """一条归了类的上游失败。认不出类别的落回通用的「生成失败」,原文照带。"""
    key = UPSTREAM_ERROR_KEYS.get(category or "", "providerErr_generationFailed")
    return GenerationAdapterError(key, vendor=vendor, detail=str(detail)[:500])


def categorized_http_error(vendor: str, exc: httpx.HTTPError, credential: str | None) -> GenerationAdapterError:
    """同 `adapter_http_error`,但按状态码归类 —— 用户看到的是「密钥不对 / 余额不足 / 限流了」,
    而不是一句「请求失败」加一段英文回包。上游原文照样在 `detail` 里。"""
    response = getattr(exc, "response", None)
    category = http_status_category(response.status_code) if response is not None else None
    detail = http_error_detail(exc, credential)
    if category is None:
        return GenerationAdapterError("providerErr_requestFailed", vendor=vendor, detail=detail)
    return upstream_error(vendor, category, detail)


def http_error_detail(exc: httpx.HTTPError, credential: str | None) -> str:
    """上游 HTTP 失败的原文:httpx 那句 + 回包正文(截断、脱敏)。"""
    message = str(exc)
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            body = response.text.strip()
        except Exception:  # noqa: BLE001 - best-effort diagnostics only
            body = ""
        if body:
            message = f"{message}; body: {body[:800]}"
    return sanitize_adapter_error(message, credential)


class PollAnswerUnreadable(ValueError):
    """轮询的回答不是一份 JSON 对象:代理 / 网关回了一页 HTML,或者空串。由轮询循环抛(见 adapters/shared/polling)。"""


def transient_poll_failure(exc: BaseException) -> bool:
    """等远端时这一次没问到,是不是「过一会儿再问就好」(轮询循环据此退避再问,而不是放弃付过钱的远端任务)。

    是:连接层的(断网、超时、对面断开)、对面一时答不上来的(429 / 5xx)、回答不是 JSON 对象的(网关页)。
    不是:401 / 403 / 404 这类说的是凭据或任务本身,再问一百遍也一样;用户取消(`core/abort.RequestAborted`,
    它是 RequestError 而不是 TransportError)也不是。
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return is_retryable_status(exc.response.status_code)
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, PollAnswerUnreadable)
