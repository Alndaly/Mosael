"""上游 HTTP 失败 → 一条带文案 key 的 GenerationAdapterError。只加工别人抛出的 httpx 异常,自己不发请求。"""

from __future__ import annotations

from typing import Any

import httpx

from app.ai.providers.contracts.generation import GenerationAdapterError, sanitize_adapter_error


def adapter_http_error(vendor: str, exc: httpx.HTTPError, credential: str | None) -> GenerationAdapterError:
    """Surface provider HTTP failures with the response body when available.

    httpx's default message links to MDN but omits the provider's JSON error, which is the
    part users need to fix a model name, unsupported size, or missing capability.

    返回的是**一条带 key 的错误**,不是一句拼好的话:「{vendor} 请求失败:…」这半句要跟着读的人
    的语言走,后面那段上游原文(已脱敏)原样放进 `detail`。
    """
    return GenerationAdapterError("providerErr_requestFailed", vendor=vendor, detail=http_error_detail(exc, credential))


#: 供应商回话里**常见的几类失败**,各对应一句按读的人语言翻好的话。上游原文(已脱敏)仍放进
#: `detail`,我们不翻、也不猜它;类别只是让用户一眼知道下一步是**换钥匙、充值、等一会儿、改提示词
#: 还是改参数** —— 此前一律是「{vendor} 生成失败:1008 insufficient balance」,中文界面上只剩一串
#: 英文和一个数字。
#:
#: 哪个错误码属于哪一类由各家 Adapter 按自己的文档判(错误码表各家各一套),这里只收类别。
UPSTREAM_ERROR_KEYS = {
    "auth": "providerErr_upstreamAuth",
    "balance": "providerErr_upstreamBalance",
    "rate_limited": "providerErr_upstreamRateLimited",
    "content_blocked": "providerErr_upstreamContentBlocked",
    "invalid_params": "providerErr_upstreamInvalidParams",
    "not_entitled": "providerErr_upstreamNotEntitled",
    "unavailable": "providerErr_upstreamUnavailable",
}


def upstream_error(vendor: str, category: str | None, detail: Any) -> GenerationAdapterError:
    """一条归了类的上游失败。认不出类别的落回通用的「生成失败」,原文照带。"""
    key = UPSTREAM_ERROR_KEYS.get(category or "", "providerErr_generationFailed")
    return GenerationAdapterError(key, vendor=vendor, detail=str(detail)[:500])


def http_status_category(status: int) -> str | None:
    """HTTP 状态码 → 失败类别(见 UPSTREAM_ERROR_KEYS)。只收各家通用的那几个含义;
    认不出的回 None,由调用方落回通用的「请求失败」。"""
    if status in (401, 403):
        return "auth"
    if status == 402:
        return "balance"
    if status == 429:
        return "rate_limited"
    if status in (400, 422):
        return "invalid_params"
    if status >= 500:
        return "unavailable"
    return None


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
