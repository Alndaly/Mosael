"""订阅额度的响应解析。

三家的响应形状是照各自官方/CLI 实际返回的字段写的,这里用记录下来的形状做回归 ——
解析器是纯函数,而真正会坏的地方正是"对方字段名变了"和"某个字段这次没给"。

每条断言都对应一个具体的误报:分母不存在时不能编、unlimited 时不能显示成 0、
少一个窗口时不能整体失败。
"""

from __future__ import annotations

import pytest

from app.domain.provider_quota import (
    QuotaUnavailable,
    access_token,
    parse_anthropic,
    parse_codex,
    parse_openrouter,
    supports_quota,
)


def test_anthropic_两个滚动窗口():
    snapshot = parse_anthropic(
        {
            "five_hour": {"utilization": 42.5, "resets_at": "2026-08-01T12:00:00Z"},
            "seven_day": {"utilization": 8.0, "resets_at": "2026-08-05T00:00:00Z"},
        }
    )
    keys = [m["key"] for m in snapshot["metrics"]]
    assert keys == ["five_hour", "seven_day"]
    assert snapshot["metrics"][0]["used_percent"] == 42.5
    assert snapshot["metrics"][0]["window_seconds"] == 5 * 3600
    assert snapshot["metrics"][0]["kind"] == "percent"


def test_anthropic_只给一个窗口时不整体失败():
    """不同计划暴露的窗口不一样。要求两个都在,会让只有 5 小时窗口的计划一条都看不到。"""
    snapshot = parse_anthropic({"five_hour": {"utilization": 10}})
    assert len(snapshot["metrics"]) == 1


def test_anthropic_一个都认不出来才算失败():
    with pytest.raises(QuotaUnavailable):
        parse_anthropic({"something_else": 1})


def test_codex_窗口长度取响应给的值():
    """各计划窗口长度不同,写死 5h/7d 会在界面上标错周期。"""
    snapshot = parse_codex(
        {
            "plan_type": "pro",
            "rate_limit": {
                "primary_window": {"used_percent": 12, "limit_window_seconds": 18000, "reset_at": "x"},
                "secondary_window": {"used_percent": 3, "limit_window_seconds": 604800},
            },
        }
    )
    assert snapshot["plan"] == "pro"
    assert [m["window_seconds"] for m in snapshot["metrics"]] == [18000, 604800]


def test_codex_不限量的信用点不报成余额零():
    snapshot = parse_codex(
        {
            "rate_limit": {"primary_window": {"used_percent": 1, "limit_window_seconds": 18000}},
            "credits": {"has_credits": True, "unlimited": True, "balance": 0},
        }
    )
    credits = next(m for m in snapshot["metrics"] if m["key"] == "credits")
    assert credits["unlimited"] is True
    assert credits["limit"] is None  # 显示成「余额 0」比不显示更误导


def test_openrouter_不限额时不编分母():
    snapshot = parse_openrouter({"data": {"limit": None, "usage": 3.25, "is_free_tier": False}})
    credits = snapshot["metrics"][0]
    assert credits["used"] == 3.25
    assert credits["limit"] is None
    assert credits["unlimited"] is True
    assert credits["unit"] == "USD"


def test_openrouter_周期用量各自成条():
    snapshot = parse_openrouter({"data": {"limit": 10, "usage": 4, "usage_daily": 1, "usage_monthly": 4}})
    keys = [m["key"] for m in snapshot["metrics"]]
    assert keys == ["credits", "usage_daily", "usage_monthly"]


def test_未接入的供应商明确不支持():
    """kimi-coding / github-copilot / xai 目前没有可验证的公开端点。留白而不是猜一个地址 ——
    猜错的表现是永远查不出来,却看不出为什么。"""
    assert supports_quota("anthropic") is True
    assert supports_quota("kimi-coding") is False
    assert supports_quota(None) is False


@pytest.mark.parametrize(
    "credential,expected",
    [
        ({"access_token": " abc "}, "abc"),
        ({"accessToken": "xyz"}, "xyz"),
        ({"auth": {"apiKey": "nested"}}, "nested"),
        ({"access_token": ""}, None),
        (None, None),
    ],
)
def test_取访问令牌兼容各家键名(credential, expected):
    assert access_token(credential) == expected
