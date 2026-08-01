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
    parse_copilot,
    parse_kimi,
    parse_openrouter,
    parse_xai,
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


def test_kimi_剩余量归一成已用():
    """这家给的是 remaining。界面其余几家都是「已用 / 上限」,这里报剩余会让同一排数字
    一半是"用了多少"一半是"还剩多少",读起来要来回换算。"""
    snapshot = parse_kimi(
        {
            "usage": {"limit": 1000, "remaining": 250, "resetTime": "2026-08-01T00:00:00Z"},
            "limits": [{"window": {"duration": 5, "timeUnit": "TIME_UNIT_HOUR"}, "detail": {"limit": 300, "remaining": 90}}],
            "user": {"membership": {"level": "pro"}},
        }
    )
    assert snapshot["plan"] == "pro"
    total = snapshot["metrics"][0]
    assert total["used"] == 750 and total["limit"] == 1000
    window = snapshot["metrics"][1]
    assert window["used"] == 210
    # duration + timeUnit 要一起算:只看 duration 会把「5 小时」当成「5 秒」。
    assert window["window_seconds"] == 5 * 3600


def test_kimi_未知时间单位不瞎猜():
    snapshot = parse_kimi({"limits": [{"window": {"duration": 5, "timeUnit": "TIME_UNIT_FORTNIGHT"}, "detail": {"limit": 1, "remaining": 0}}]})
    assert snapshot["metrics"][0]["window_seconds"] is None


def test_xai_按需上限单独成条():
    """按需上限不能加进月度上限:那会让「月度还剩很多」看起来成立,实际早已进入按需计费。"""
    snapshot = parse_xai({"config": {"used": 80, "monthlyLimit": 100, "onDemandCap": 500}, "subscription_tier_display": "SuperGrok"})
    assert snapshot["plan"] == "SuperGrok"
    assert [m["key"] for m in snapshot["metrics"]] == ["monthly", "on_demand"]
    assert snapshot["metrics"][0]["limit"] == 100


def test_copilot_按响应里实际有的项报():
    """三种账户模式返回的结构不同,要求固定形状会让其中两种一条都读不出来。"""
    snapshot = parse_copilot(
        {
            "quota_snapshots": {
                "premium_interactions": {"remaining": 60, "entitlement": 300},
                "chat": {"remaining": 0, "entitlement": 0, "unlimited": True},
            },
            "quota_reset_date": "2026-09-01",
        }
    )
    keys = sorted(m["key"] for m in snapshot["metrics"])
    assert keys == ["copilot_chat", "copilot_premium_interactions"]
    premium = next(m for m in snapshot["metrics"] if m["key"] == "copilot_premium_interactions")
    assert premium["used"] == 240
    assert premium["resets_at"] == "2026-09-01"


def test_六家都接入了():
    for provider in ("anthropic", "openai-codex", "openrouter", "kimi-coding", "xai", "github-copilot"):
        assert supports_quota(provider) is True
    assert supports_quota("some-future-vendor") is False
    assert supports_quota(None) is False


@pytest.mark.parametrize(
    "credential,expected",
    [
        # pi 的真实形状:OAuth 用 access,API Key 用 key。第一版按 access_token / api_key 去取,
        # 六家一家都取不到,界面上全是"尚未授权登录"而档案显示已授权。
        ({"type": "oauth", "access": "tok", "refresh": "r", "expires": 123}, "tok"),
        ({"type": "api_key", "key": "sk-1"}, "sk-1"),
        ({"access_token": " abc "}, "abc"),
        ({"accessToken": "xyz"}, "xyz"),
        ({"auth": {"apiKey": "nested"}}, "nested"),
        ({"access_token": ""}, None),
        (None, None),
    ],
)
def test_取访问令牌兼容各家键名(credential, expected):
    assert access_token(credential) == expected


def test_过期判定按毫秒():
    """expires 是 epoch **毫秒**(pi 里判的是 Date.now() >= expires)。
    按秒比会让每一份凭据都显示成过期 —— 差三个数量级。"""
    from app.domain.provider_quota import is_expired

    now_ms = 1_700_000_000_000
    assert is_expired({"expires": now_ms - 1}, now_ms=now_ms) is True
    assert is_expired({"expires": now_ms + 60_000}, now_ms=now_ms) is False
    # API Key 型没有 expires,不能被当成过期
    assert is_expired({"type": "api_key", "key": "sk"}, now_ms=now_ms) is False
    assert is_expired(None, now_ms=now_ms) is False


def test_过期与无权限是两种错():
    """403 基本是"这个端点不给这个账号用",和过期是两回事。混成一句会让用户
    反复去重新授权,而问题根本不在授权上。"""
    from app.domain.provider_quota import CredentialExpired, QuotaUnavailable

    assert issubclass(CredentialExpired, QuotaUnavailable)


def test_过期的凭据不发请求直接报过期():
    from app.domain.provider_quota import CredentialExpired, fetch_quota

    with pytest.raises(CredentialExpired):
        fetch_quota("anthropic", {"type": "oauth", "access": "tok", "expires": 1})


def test_档案同时报出_已授权_与_是否过期():
    """`oauth_linked` 只说"存过凭据",不说"现在有效"。两者分开,卡片才能如实说出
    「已授权但令牌过期」—— 否则用户看着"已授权"却处处碰壁,只会以为是别的地方坏了。"""
    import time as _time

    from app.core.db import SessionLocal
    from app.db.models import ProviderProfile
    from tests.util import fresh_client

    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    past = int((_time.time() - 3600) * 1000)
    with SessionLocal() as db:
        db.add(
            ProviderProfile(
                name="过期的订阅",
                vendor="anthropic",
                base_url="",
                api_key="",
                auth_type="oauth",
                oauth_credential={"type": "oauth", "access": "tok", "refresh": "r", "expires": past},
            )
        )
        db.commit()
    rows = client.get("/api/settings/providers").json()
    row = next(r for r in rows if r["name"] == "过期的订阅")
    assert row["oauth_linked"] is True
    assert row["oauth_expired"] is True
