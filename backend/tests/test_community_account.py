"""社区账号(ADR 0026 §3「桌面应用」):设备授权、令牌的存放、轮换、single-flight、吊销。

对面是 tests/community_fake 里的假社区服务 —— 它比真服务更挑剔:刷新令牌用过一次再用就判盗、吊销整个
会话,不给宽限期。所以「几个请求同时撞上 401 只刷新一次」在这里是真的被验了,不是碰巧没撞上。
"""

from __future__ import annotations

import sqlite3
import threading

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import CommunityAccount
from app.domain.community import NotConnected, SignedOut, Unreachable, accounts, device
from app.domain.community.accounts import CommunityClient
from tests.community_fake import ORIGIN, connect, install
from tests.util import user_id


def _client() -> CommunityClient:
    with SessionLocal() as db:
        return CommunityClient.for_user(db, user_id())


def _row() -> CommunityAccount | None:
    with SessionLocal() as db:
        return db.scalar(select(CommunityAccount))


# --- 设备授权 -------------------------------------------------------------------


def test_没配社区时状态说得清(monkeypatch) -> None:
    fake, client, _clock = install(monkeypatch)
    client.put("/api/admin/community", json={"url": ""})
    status = client.get("/api/community/status").json()
    assert status["configured"] is False and status["connected"] is False
    refused = client.post("/api/community/connect")
    assert refused.status_code == 409
    assert "社区地址" in refused.json()["detail"]
    assert fake.calls == []


def test_设备授权_等到网页上点了允许就连上(monkeypatch) -> None:
    fake, client, clock = install(monkeypatch)
    started = client.post("/api/community/connect").json()
    # 验证地址补成了社区站点上的绝对地址;码交给界面显示。
    assert started["verification_uri"] == f"{ORIGIN}/zh/device?code={started['user_code']}"
    assert client.get("/api/community/status").json()["pending"]["user_code"] == started["user_code"]

    # 没到 interval:一次请求都不发。
    assert client.post("/api/community/connect/poll").json()["state"] == "pending"
    assert fake.count("/auth/device/token") == 0

    clock.advance(5)
    assert client.post("/api/community/connect/poll").json()["state"] == "pending"  # 428 authorization_pending
    assert fake.count("/auth/device/token") == 1

    fake.approve(started["user_code"])
    clock.advance(5)
    polled = client.post("/api/community/connect/poll").json()
    assert polled["state"] == "connected"
    assert polled["status"]["connected"] is True
    assert polled["status"]["handle"] == "alice"
    assert polled["status"]["pending"] is None


def test_slow_down_把间隔加五秒(monkeypatch) -> None:
    fake, client, clock = install(monkeypatch)
    started = client.post("/api/community/connect").json()
    fake.device(started["user_code"]).slow_downs = 1

    clock.advance(5)
    assert client.post("/api/community/connect/poll").json()["state"] == "pending"
    assert fake.count("/auth/device/token") == 1

    # 原来的 5 秒已经不够了:再过 5 秒不发请求,要等到 10 秒。
    clock.advance(5)
    client.post("/api/community/connect/poll")
    assert fake.count("/auth/device/token") == 1
    clock.advance(5)
    fake.approve(started["user_code"])
    assert client.post("/api/community/connect/poll").json()["state"] == "connected"
    assert fake.count("/auth/device/token") == 2


def test_设备码过期_本机先知道_不再去问(monkeypatch) -> None:
    fake, client, clock = install(monkeypatch)
    client.post("/api/community/connect")
    clock.advance(601)
    assert client.post("/api/community/connect/poll").json()["state"] == "expired"
    assert fake.count("/auth/device/token") == 0
    assert client.get("/api/community/status").json()["pending"] is None


def test_服务端说过期了也按过期(monkeypatch) -> None:
    fake, client, clock = install(monkeypatch)
    started = client.post("/api/community/connect").json()
    fake.device(started["user_code"]).expired = True
    clock.advance(5)
    assert client.post("/api/community/connect/poll").json()["state"] == "expired"
    clock.advance(5)
    assert client.post("/api/community/connect/poll").json()["state"] == "idle"


def test_拒绝与取消(monkeypatch) -> None:
    fake, client, clock = install(monkeypatch)
    started = client.post("/api/community/connect").json()
    fake.device(started["user_code"]).denied = True
    clock.advance(5)
    assert client.post("/api/community/connect/poll").json()["state"] == "denied"

    client.post("/api/community/connect")
    assert client.delete("/api/community/connect").status_code == 204
    clock.advance(5)
    assert client.post("/api/community/connect/poll").json()["state"] == "idle"


def test_刷新令牌加密落盘_不出接口(monkeypatch) -> None:
    fake, client, clock = install(monkeypatch)
    status = connect(client, fake, clock)
    refresh = fake.live_refresh_token()
    assert refresh not in str(status)
    assert refresh not in client.get("/api/community/status").text
    # 库文件里读不到明文 —— 和服务商密钥同一种加密列。
    with sqlite3.connect(settings.db_path) as raw:
        stored = raw.execute("select refresh_token from community_accounts").fetchone()[0]
    assert stored and refresh not in stored
    assert _row().refresh_token == refresh


# --- 续期 ------------------------------------------------------------------------


def test_提前续期_轮换的新刷新令牌先落盘再用(monkeypatch) -> None:
    fake, client, clock = install(monkeypatch)
    connect(client, fake, clock)
    first = fake.live_refresh_token()

    seen: list[bool] = []

    def check_disk(_request) -> None:
        # 新的访问令牌第一次被用的时候,轮换来的新刷新令牌必须已经提交进库。
        seen.append(_row().refresh_token == fake.live_refresh_token())

    fake.on_me = check_disk
    clock.advance(900 - 30)  # 离过期不到 60 秒:先续再发
    assert _client().call("GET", "/me")["handle"] == "alice"
    assert fake.refresh_calls() == 1
    assert seen == [True]
    assert _row().refresh_token != first
    # 旧的那枚已经换掉了:再用就是重用。
    assert fake.refresh_tokens[first][1] is True


def test_几个请求同时撞上_401_只刷新一次(monkeypatch) -> None:
    fake, client, clock = install(monkeypatch)
    connect(client, fake, clock)
    fake.reject_current_access_tokens()
    fake.refresh_delay = 0.2

    results: list[object] = []
    barrier = threading.Barrier(6)

    def one() -> None:
        barrier.wait()
        try:
            results.append(_client().call("GET", "/me")["handle"])
        except Exception as exc:  # noqa: BLE001 — 收集起来断言
            results.append(exc)

    threads = [threading.Thread(target=one) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(10)
    assert results == ["alice"] * 6, results
    assert fake.refresh_calls() == 1
    # 会话没有被判盗:假服务端对重用是零容忍的。
    assert not any(session.revoked for session in fake.sessions.values())


def test_刷新令牌被吊销_删掉本机的_报社区账号已退出(monkeypatch) -> None:
    fake, client, clock = install(monkeypatch)
    connect(client, fake, clock)
    fake.revoke_all_sessions()
    with pytest.raises(SignedOut) as raised:
        _client().call("GET", "/me")
    assert str(raised.value) == "社区账号已退出,请重新连接"
    assert _row() is None
    assert client.get("/api/community/status").json()["connected"] is False
    with SessionLocal() as db, pytest.raises(NotConnected):
        CommunityClient.for_user(db, user_id())


def test_续期之后还是_401_也删掉(monkeypatch) -> None:
    fake, client, clock = install(monkeypatch)
    connect(client, fake, clock)
    fake.always_unauthorized = True
    with pytest.raises(SignedOut):
        _client().call("GET", "/me")
    assert fake.refresh_calls() == 1
    assert _row() is None


def test_连不上不算退出(monkeypatch) -> None:
    fake, client, clock = install(monkeypatch)
    connect(client, fake, clock)
    fake.refresh_status = 503
    clock.advance(900)
    with pytest.raises(Unreachable):
        _client().call("GET", "/me")
    assert _row() is not None


def test_断开_请社区吊销会话再删本机的(monkeypatch) -> None:
    fake, client, clock = install(monkeypatch)
    connect(client, fake, clock)
    assert client.post("/api/community/disconnect").status_code == 204
    assert fake.count("/auth/logout") == 1
    assert all(session.revoked for session in fake.sessions.values())
    assert _row() is None
    assert client.get("/api/community/status").json()["connected"] is False


def test_换了社区地址_旧账号不算连着(monkeypatch) -> None:
    fake, client, clock = install(monkeypatch)
    connect(client, fake, clock)
    assert client.put("/api/admin/community", json={"url": "https://other.test"}).status_code == 200
    assert client.get("/api/community/status").json()["connected"] is False


def test_社区地址只收站点根(monkeypatch) -> None:
    _fake, client, _clock = install(monkeypatch)
    for bad in ("ftp://x.test", "https://x.test/api", "mosael.com"):
        assert client.put("/api/admin/community", json={"url": bad}).status_code == 422, bad
    saved = client.put("/api/admin/community", json={"url": "https://x.test/"}).json()
    assert saved["url"] == "https://x.test"
    assert client.get("/api/admin/community").json()["default_url"] == "https://mosael.com"


def test_默认社区地址就是官网(monkeypatch) -> None:
    """默认值和官网 `SITE.url` 是同一个站点 —— 一处改了另一处没改,应用就连到一个不存在的社区上。"""
    import re
    from pathlib import Path

    from app.db.models import DEFAULT_COMMUNITY_URL

    source = (Path(__file__).resolve().parents[2] / "website" / "src" / "lib" / "site.ts").read_text(encoding="utf-8")
    match = re.search(r'url:\s*"([^"]+)"', source)
    assert match and match.group(1) == DEFAULT_COMMUNITY_URL


def test_内存里的令牌与流程可以清(monkeypatch) -> None:
    fake, client, clock = install(monkeypatch)
    client.post("/api/community/connect")
    device.reset_for_tests()
    accounts.reset_for_tests()
    assert client.get("/api/community/status").json()["pending"] is None
