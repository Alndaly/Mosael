"""订阅计划的额度查询。

**为什么是手动点击而不是自动轮询**:这些端点没有一个是官方文档承诺过的公开接口
(Anthropic 的 `oauth/usage`、Codex 的 `codex/usage` 都是各自 CLI 内部在用),自动轮询
既容易撞上对方的限流桶,也会在对方改接口时变成后台里一直在失败的定时任务。用户点一下
才查一次,失败了也只是这一次点击的事。

**为什么不归一成一个数字**:各家的额度类型和周期根本对不齐 —— Anthropic 是两个滚动窗口
的利用率百分比,Codex 是两个窗口的百分比外加一份可选的信用点余额,OpenRouter 是美元额度。
硬压成"剩余 xx%"要么丢信息,要么得为它编一个不存在的分母。所以归一化只做到「一组指标」
这一层:每条指标自带 kind(百分比还是余额)、周期长度和重置时间,怎么展示交给前端。

pi 在这块不提供任何能力(六家 Provider 里没有配额查询,也不解析限流响应头),所以这里
按家实现。**查不到就明说查不到**,不猜、不留一个恒为空的进度条 —— 后者会让用户以为额度
用完了。
"""

from __future__ import annotations

import time
from typing import Any, Callable

import httpx

#: 单次查询的超时。用户是点了按钮在等,不能挂太久。
TIMEOUT_SECONDS = 12.0

#: Anthropic 的 usage 端点按 User-Agent 分限流桶,不带 claude-code/* 会落进一个很紧的桶里
#: 持续 429。这不是伪装成别的客户端 —— 我们确实是在用它签发给该订阅的凭据查它自己的额度。
_CLAUDE_UA = "claude-code/1.0 (Open Studio)"


class QuotaUnavailable(RuntimeError):
    """这家供应商没有可查的额度接口,或本次查询失败。"""


def _percent_metric(
    key: str, used_percent: float | None, *, window_seconds: int | None, resets_at: str | None
) -> dict[str, Any]:
    return {
        "key": key,
        "kind": "percent",
        "used_percent": used_percent,
        "used": None,
        "limit": None,
        "unit": None,
        "window_seconds": window_seconds,
        "resets_at": resets_at,
    }


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed else None  # NaN 挡掉


# ── 各家的响应解析(纯函数,便于按真实响应形状测试)────────────────────────────


def parse_anthropic(payload: dict[str, Any]) -> dict[str, Any]:
    """`GET https://claude.ai/api/oauth/usage`。

    两个滚动窗口:five_hour 与 seven_day,给的都是利用率(0–100)。字段可能只出现一个
    (不同计划暴露的窗口不同),所以逐个判断而不是要求都在。
    """
    metrics: list[dict[str, Any]] = []
    for key, seconds in (("five_hour", 5 * 3600), ("seven_day", 7 * 86400)):
        window = payload.get(key)
        if not isinstance(window, dict):
            continue
        used = _number(window.get("utilization"))
        if used is None:
            continue
        resets = window.get("resets_at") or window.get("reset_at")
        metrics.append(
            _percent_metric(key, used, window_seconds=seconds, resets_at=str(resets) if resets else None)
        )
    if not metrics:
        raise QuotaUnavailable("响应里没有可识别的用量窗口")
    plan = payload.get("plan") or payload.get("subscription_type")
    return {"plan": str(plan) if plan else None, "metrics": metrics}


def parse_codex(payload: dict[str, Any]) -> dict[str, Any]:
    """`GET /api/codex/usage`(ChatGPT 后端)。

    两个窗口 primary/secondary,窗口长度由响应自己给(`limit_window_seconds`)而不是我们
    假设 5h/7d —— 各计划的窗口不一样,写死会在界面上标错周期。另有一份可选的信用点余额。
    """
    metrics: list[dict[str, Any]] = []
    rate_limit = payload.get("rate_limit")
    if isinstance(rate_limit, dict):
        for key in ("primary_window", "secondary_window"):
            window = rate_limit.get(key)
            if not isinstance(window, dict):
                continue
            used = _number(window.get("used_percent"))
            if used is None:
                continue
            resets = window.get("reset_at") or window.get("resets_at")
            metrics.append(
                _percent_metric(
                    key,
                    used,
                    window_seconds=int(_number(window.get("limit_window_seconds")) or 0) or None,
                    resets_at=str(resets) if resets else None,
                )
            )
    credits = payload.get("credits")
    if isinstance(credits, dict) and credits.get("has_credits"):
        # unlimited 时不给数字:显示一个"余额 0"比不显示更误导。
        balance = None if credits.get("unlimited") else _number(credits.get("balance"))
        metrics.append(
            {
                "key": "credits",
                "kind": "balance",
                "used_percent": None,
                "used": None,
                "limit": balance,
                "unit": "credit",
                "window_seconds": None,
                "resets_at": None,
                "unlimited": bool(credits.get("unlimited")),
            }
        )
    if not metrics:
        raise QuotaUnavailable("响应里没有可识别的额度窗口")
    plan = payload.get("plan_type")
    return {"plan": str(plan) if plan else None, "metrics": metrics}


def parse_openrouter(payload: dict[str, Any]) -> dict[str, Any]:
    """`GET https://openrouter.ai/api/v1/key`。

    这家是**花掉多少美元**而不是百分比,而且 limit 可能为 null(不限额)。limit 为空时
    只报已用量,不去编一个分母。
    """
    data = payload.get("data")
    if not isinstance(data, dict):
        raise QuotaUnavailable("响应缺少 data")
    limit = _number(data.get("limit"))
    used = _number(data.get("usage"))
    if used is None and limit is None:
        raise QuotaUnavailable("响应里没有可识别的额度")
    metrics = [
        {
            "key": "credits",
            "kind": "balance",
            "used_percent": None,
            "used": used,
            "limit": limit,
            "unit": "USD",
            "window_seconds": None,
            "resets_at": None,
            "unlimited": limit is None,
        }
    ]
    for key, window_seconds in (("usage_daily", 86400), ("usage_weekly", 7 * 86400), ("usage_monthly", 30 * 86400)):
        amount = _number(data.get(key))
        if amount is None:
            continue
        metrics.append(
            {
                "key": key,
                "kind": "balance",
                "used_percent": None,
                "used": amount,
                "limit": None,
                "unit": "USD",
                "window_seconds": window_seconds,
                "resets_at": None,
                "unlimited": False,
            }
        )
    plan = "free" if data.get("is_free_tier") else None
    return {"plan": plan, "metrics": metrics}


# ── 取访问令牌 ──────────────────────────────────────────────────────────────


def access_token(credential: dict[str, Any] | None) -> str | None:
    """从 pi 的 Credential 里取访问令牌。

    各家键名不统一(pi 原样存的),挨个试。取不到就返回 None —— 让调用方报"未登录",
    比拿着空串去请求换回一个 401 强。
    """
    if not isinstance(credential, dict):
        return None
    for key in ("access_token", "accessToken", "token", "api_key", "apiKey"):
        value = credential.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    nested = credential.get("auth") or credential.get("credential")
    if isinstance(nested, dict):
        return access_token(nested)
    return None


# ── 按家抓取 ────────────────────────────────────────────────────────────────


def _get_json(url: str, headers: dict[str, str], *, proxies_from_env: bool = True) -> dict[str, Any]:
    with httpx.Client(timeout=TIMEOUT_SECONDS, trust_env=proxies_from_env) as client:
        response = client.get(url, headers=headers)
        if response.status_code == 401 or response.status_code == 403:
            raise QuotaUnavailable("凭据已失效,请重新授权登录")
        if response.status_code == 429:
            raise QuotaUnavailable("对方限流,稍后再试")
        response.raise_for_status()
        payload = response.json()
    if not isinstance(payload, dict):
        raise QuotaUnavailable("响应不是对象")
    return payload


def _fetch_anthropic(token: str) -> dict[str, Any]:
    return parse_anthropic(
        _get_json(
            "https://claude.ai/api/oauth/usage",
            {"Authorization": f"Bearer {token}", "User-Agent": _CLAUDE_UA, "Accept": "application/json"},
        )
    )


def _fetch_codex(token: str) -> dict[str, Any]:
    return parse_codex(
        _get_json(
            "https://chatgpt.com/backend-api/codex/usage",
            {"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
    )


def _fetch_openrouter(token: str) -> dict[str, Any]:
    return parse_openrouter(
        _get_json(
            "https://openrouter.ai/api/v1/key",
            {"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
    )


#: pi_provider → 抓取函数。**不在这张表里的供应商就是查不到**,界面据此显示"该供应商不提供
#: 额度查询"而不是一个空进度条。kimi-coding / github-copilot / xai 目前没有找到可验证的
#: 公开端点,宁可留白也不写一个猜出来的地址 —— 猜错的表现是永远查不出来,却看不出为什么。
FETCHERS: dict[str, Callable[[str], dict[str, Any]]] = {
    "anthropic": _fetch_anthropic,
    "openai-codex": _fetch_codex,
    "openrouter": _fetch_openrouter,
}


def supports_quota(pi_provider: str | None) -> bool:
    return bool(pi_provider) and pi_provider in FETCHERS


def fetch_quota(pi_provider: str | None, credential: dict[str, Any] | None) -> dict[str, Any]:
    """查一次额度。返回归一化快照;查不到一律抛 QuotaUnavailable。"""
    fetcher = FETCHERS.get(pi_provider or "")
    if fetcher is None:
        raise QuotaUnavailable("该供应商不提供额度查询")
    token = access_token(credential)
    if not token:
        raise QuotaUnavailable("尚未授权登录")
    try:
        snapshot = fetcher(token)
    except QuotaUnavailable:
        raise
    except httpx.HTTPError as exc:
        raise QuotaUnavailable(f"查询失败:{exc}") from exc
    except (ValueError, KeyError, TypeError) as exc:
        # 对方改了响应形状。报出来,别把它当成"额度为零"。
        raise QuotaUnavailable(f"响应无法解析:{exc}") from exc
    snapshot["fetched_at"] = time.time()
    return snapshot
