"""列连接是一次**读**,不该卡在别人的服务器上。

用户撞到的:设置页一直显示「正在连接后端…」,而后端日志里是
`刷新 xAL 的订阅令牌失败:OAuth refresh failed for xai: fetch failed`。

`GET /api/settings/providers` 在返回之前会替每一条**过期的订阅连接**去刷新令牌,而刷新是:
起一个 Node 子进程(pi sidecar)→ 向那家供应商发一次网络请求 → 最长等 60 秒。断网或那家挂掉时,
每条这样的连接都要等到超时,而且是**串行**的。两条订阅连接就是两次。

于是一件本地的、纯读的事(告诉我我配了哪些连接)被一件远程的、可选的事(顺手把令牌刷了)拖住。
判据很清楚:**这个接口要回答的问题,不需要出网就能回答。**

刷新本身要留着 —— 它解决的是真问题(订阅 access token 几小时就过期,隔夜打开必然看到一行
「已过期」,而它只要被用到就会自己好)。留着,但挪到请求之外:先把列表给他,刷新在后台跑,
下一次拉列表时状态自己就对了。
"""

from __future__ import annotations

import threading
import time

from app.api.routes.settings import provider_profiles as settings_routes
from tests.util import add_provider, fresh_client
from app.core.db import SessionLocal


def _expired_subscription(client) -> None:
    """一条 access token 已经过期的订阅连接。"""
    past = int((time.time() - 3600) * 1000)
    with SessionLocal() as db:
        add_provider(
            db,
            name="掉线的订阅",
            vendor="anthropic",
            base_url="",
            api_key="",
            auth_type="oauth",
            oauth_credential={"type": "oauth", "access": "tok", "refresh": "r", "expires": past},
            model="claude",
            capability_ids=["chat"],
            make_default=False,
        )
        db.commit()


def test_a_slow_refresh_does_not_hold_up_the_list(monkeypatch) -> None:
    """刷新卡住时,列表照样立刻返回。"""
    started = threading.Event()
    release = threading.Event()

    def slow_refresh(**kwargs):
        started.set()
        release.wait(10)  # 模拟 fetch 卡到超时
        return True

    monkeypatch.setattr(settings_routes, "refresh_oauth_credential", slow_refresh)
    settings_routes._refresh_failed_at.clear()

    client = fresh_client()
    _expired_subscription(client)

    began = time.monotonic()
    listed = client.get("/api/settings/providers")
    elapsed = time.monotonic() - began
    release.set()

    assert listed.status_code == 200, listed.text
    assert elapsed < 2.0, f"列连接等了 {elapsed:.1f} 秒 —— 它卡在刷新上了"


def test_the_refresh_still_happens(monkeypatch) -> None:
    """挪到后台不等于不做 —— 过期的令牌仍然会被刷。"""
    calls: list[dict] = []

    def record(**kwargs):
        calls.append(kwargs)
        return True

    monkeypatch.setattr(settings_routes, "refresh_oauth_credential", record)
    settings_routes._refresh_failed_at.clear()

    client = fresh_client()
    _expired_subscription(client)
    client.get("/api/settings/providers")

    deadline = time.time() + 5
    while not calls and time.time() < deadline:
        time.sleep(0.05)
    assert calls, "刷新没被触发 —— 挪到后台之后它就没人做了"


def test_a_failing_refresh_never_reaches_the_response(monkeypatch) -> None:
    """刷不动是**那条连接**的事,不该变成整页的错误 —— 断网时每条订阅连接都会刷不动。"""
    def boom(**kwargs):
        raise settings_routes.AdapterError("OAuth refresh failed: fetch failed")

    monkeypatch.setattr(settings_routes, "refresh_oauth_credential", boom)
    settings_routes._refresh_failed_at.clear()

    client = fresh_client()
    _expired_subscription(client)

    listed = client.get("/api/settings/providers")

    assert listed.status_code == 200, listed.text
    assert any(row["name"] == "掉线的订阅" for row in listed.json())


# ---------------------------------------------------------------------------
# 「过期」不是「要你重新授权」
# ---------------------------------------------------------------------------
def _listed(client) -> dict:
    rows = client.get("/api/settings/providers").json()
    return next(row for row in rows if row["name"] == "掉线的订阅")


def test_an_expired_token_being_refreshed_does_not_cry_wolf(monkeypatch) -> None:
    """用户撞到的:「明明授权成功了,界面却显示需要再次授权」。

    订阅计划的 access token 普遍只有几小时,过期后由后台自动刷 —— 这是协议里就有的一步,
    不是一件用户需要知道的事。而 `oauth_expired` 此前就是 `is_expired(...)`,界面把它渲染成
    红字「令牌刷新失败 · 需重新授权」。于是只要在过期窗口里打开设置页,就会看到一句
    **不成立**的话:它几秒后自己就好了。

    「过期了,正在刷」和「刷不动了,要你处理」被压成了同一个布尔值。这条钉住前者不报警。
    """
    monkeypatch.setattr(settings_routes, "refresh_oauth_credential", lambda **kw: True)
    settings_routes._refresh_failed_at.clear()

    client = fresh_client()
    _expired_subscription(client)
    row = _listed(client)
    assert row["oauth_linked"] is True
    assert row["oauth_expired"] is False, "过期但刷得动,不该让用户去重新授权"


def test_a_token_that_really_cannot_be_refreshed_does_say_so(monkeypatch) -> None:
    """反过来:真的刷不动就必须说。不然「需重新授权」这个状态等于没有了。"""
    from app.ai.sidecar.adapters import AdapterError

    def refuse(**kwargs):
        raise AdapterError("OAuth refresh failed for anthropic: fetch failed")

    monkeypatch.setattr(settings_routes, "refresh_oauth_credential", refuse)
    settings_routes._refresh_failed_at.clear()

    client = fresh_client()
    _expired_subscription(client)
    profile_id = _listed(client)["id"]

    # 第一次拉列表只是**触发**后台刷新,那时还没有"刷不动"这个事实 —— 所以先等它失败。
    deadline = time.time() + 5
    while time.time() < deadline and profile_id not in settings_routes._refresh_failed_at:
        time.sleep(0.02)
    assert profile_id in settings_routes._refresh_failed_at, "后台刷新压根没跑"

    assert _listed(client)["oauth_expired"] is True, "刷不动了却不说,用户无从知道要重新授权"


def test_a_healthy_subscription_is_never_flagged(monkeypatch) -> None:
    """没过期的连接,无论后台发生过什么,都不该显示需要重新授权。"""
    monkeypatch.setattr(settings_routes, "refresh_oauth_credential", lambda **kw: True)
    settings_routes._refresh_failed_at.clear()

    client = fresh_client()
    future = int((time.time() + 7200) * 1000)
    with SessionLocal() as db:
        add_provider(
            db, name="好好的订阅", vendor="anthropic", base_url="", api_key="", auth_type="oauth",
            oauth_credential={"type": "oauth", "access": "tok", "refresh": "r", "expires": future},
            model="claude", capability_ids=["chat"], make_default=False,
        )
        db.commit()
    row = next(r for r in client.get("/api/settings/providers").json() if r["name"] == "好好的订阅")
    assert row["oauth_linked"] is True and row["oauth_expired"] is False
