"""浏览器自动化底座:会话隔离 + 动作桥(入队→执行器 claim/report→阻塞轮询回结果)。

执行器(Electron)不在测试里,于是用 worker_client 扮演它打 /api/browser/worker/*,验证整条
后端桥的语义:分区命名空间隔离、往返返回结果、失败传播、鉴权、重启回收。
"""

from __future__ import annotations

import threading
import time

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import BrowserAction, BrowserSession
from app.domain import browser
from tests.util import fresh_client, worker_client


def _workspace() -> tuple[object, str]:
    client = fresh_client()
    return client, client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _claim(worker, timeout: float = 5.0) -> dict:
    """扮演执行器:轮询 claim 到一条动作。"""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        action = worker.post("/api/browser/worker/claim", json={"worker": "test"}).json().get("action")
        if action is not None:
            return action
        time.sleep(0.05)
    raise AssertionError("worker 没能 claim 到动作")


def test_partition_isolation_from_publish() -> None:
    _, ws = _workspace()
    with SessionLocal() as db:
        eph = browser.open_session(db, workspace_id=ws)
        assert eph.kind == "ephemeral"
        assert eph.partition == f"ephemeral-{eph.id}"
        assert not eph.partition.startswith("persist:")  # 临时=内存态,关闭即清

        named = browser.open_session(db, workspace_id=ws, kind="named", name="My Profile!")
        assert named.partition == "persist:rpa-My-Profile"  # 名字清洗进 rpa 命名空间
        assert not named.partition.startswith("persist:mibu-")  # 绝不撞发布(persist:mibu-<account>)

        # 具名会话同名复用(要跨次保留登录)。
        again = browser.open_session(db, workspace_id=ws, kind="named", name="My Profile!")
        assert again.id == named.id

    # 恶意名字也进不了发布命名空间。
    with SessionLocal() as db:
        evil = browser.open_session(db, workspace_id=ws, kind="named", name="mibu-someaccount")
        assert evil.partition == "persist:rpa-mibu-someaccount"
        assert not evil.partition.startswith("persist:mibu-")


def test_run_action_roundtrip_returns_worker_result() -> None:
    _, ws = _workspace()
    worker = worker_client()
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws).id

    holder: dict = {}

    def caller() -> None:
        try:
            holder["result"] = browser.run_action(sid, "extract", {"selector": "h1"}, timeout=10)
        except Exception as exc:  # noqa: BLE001
            holder["error"] = exc

    t = threading.Thread(target=caller)
    t.start()

    action = _claim(worker)
    assert action["action"] == "extract"
    assert action["args"] == {"selector": "h1"}
    assert action["partition"] == f"ephemeral-{sid}"  # 执行器拿到隔离分区
    worker.patch(
        "/api/browser/worker/report",
        json={"action_id": action["id"], "status": "done", "result": {"value": "Hello"}, "last_url": "https://x.test/"},
    )

    t.join(timeout=5)
    assert holder.get("result") == {"value": "Hello"}
    with SessionLocal() as db:
        assert db.get(BrowserSession, sid).last_url == "https://x.test/"  # last_url 落到会话


def test_run_action_failure_propagates() -> None:
    _, ws = _workspace()
    worker = worker_client()
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws).id

    holder: dict = {}

    def caller() -> None:
        try:
            browser.run_action(sid, "click", {"selector": "#missing"}, timeout=10)
        except browser.BrowserDomainError as exc:
            holder["error"] = str(exc)

    t = threading.Thread(target=caller)
    t.start()
    action = _claim(worker)
    worker.patch(
        "/api/browser/worker/report",
        json={"action_id": action["id"], "status": "failed", "error": "元素未找到"},
    )
    t.join(timeout=5)
    assert "元素未找到" in holder.get("error", "")


def test_run_action_rejects_closed_session() -> None:
    _, ws = _workspace()
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws).id
        browser.close_session(db, sid)
    try:
        browser.run_action(sid, "navigate", {"url": "https://x.test"}, timeout=2)
        raise AssertionError("已关闭会话不应接受动作")
    except browser.BrowserDomainError:
        pass


def test_worker_endpoints_need_worker_key() -> None:
    client, _ws = _workspace()
    # 普通用户会话(无 worker key)打 worker 端点 → 401。
    assert client.post("/api/browser/worker/claim", json={}).status_code == 401


def test_reconcile_fails_pending_and_closes_sessions() -> None:
    _, ws = _workspace()
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws).id
        db.add(BrowserAction(session_id=sid, workspace_id=ws, action="navigate", args={}, status="running"))
        db.commit()

    assert browser.reconcile_browser_state() >= 1
    with SessionLocal() as db:
        assert db.get(BrowserSession, sid).status == "closed"
        acts = db.scalars(select(BrowserAction).where(BrowserAction.session_id == sid)).all()
        assert acts and all(a.status == "failed" for a in acts)
