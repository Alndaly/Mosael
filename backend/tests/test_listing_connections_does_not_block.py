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

from app.api.routes import settings as settings_routes
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
