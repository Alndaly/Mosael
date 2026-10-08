"""上游失败的**几个类别**,以及各自那句话的文案 key。适配器归类,宿主照类别说人话。

住在契约里而不是 adapters/shared/errors:归类是适配器和宿主之间的约定 —— 适配器按各家的错误码 / 状态码判类别
(`adapters/shared/errors.upstream_error`),宿主在没有归过类的笼统失败上按同一张表补一次(`domain/failure_summary`:
画板格子和 AI 工作台上那一句)。领域层只经契约用 provider(tests/test_provider_architecture.py)。
"""

from __future__ import annotations

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


__all__ = ["UPSTREAM_ERROR_KEYS", "http_status_category"]
