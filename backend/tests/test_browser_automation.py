"""浏览器自动化底座:会话隔离 + 动作桥(入队→执行器 claim/report→阻塞轮询回结果)。

执行器(Electron)不在测试里,于是用 worker_client 扮演它打 /api/browser/worker/*,验证整条
后端桥的语义:分区命名空间隔离、往返返回结果、失败传播、鉴权、重启回收。
"""

from __future__ import annotations

import threading
import time

from sqlalchemy import select

from app.core.db import PARTITION_PREFIX, SessionLocal
from app.core.i18n import t
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
        eph = browser.open_session(db, workspace_id=ws, actor=None)
        assert eph.kind == "ephemeral"
        assert eph.partition == f"ephemeral-{eph.id}"
        assert not eph.partition.startswith("persist:")  # 临时=内存态,关闭即清

        named = browser.open_session(db, workspace_id=ws, kind="named", name="My Profile!", actor=None)
        assert named.partition == "persist:rpa-My-Profile"  # 名字清洗进 rpa 命名空间
        # 绝不撞发布账号的登录分区。前缀取自 PARTITION_PREFIX,不要写死——写死的话前缀一改,
        # 这个断言就悄悄变成在防一个已经不存在的名字,而真正的碰撞面无人看守。
        assert not named.partition.startswith(f"persist:{PARTITION_PREFIX}-")

        # 具名会话同名复用(要跨次保留登录)。
        again = browser.open_session(db, workspace_id=ws, kind="named", name="My Profile!", actor=None)
        assert again.id == named.id

    # 恶意名字也进不了发布命名空间。
    with SessionLocal() as db:
        evil = browser.open_session(db, workspace_id=ws, kind="named", name=f"{PARTITION_PREFIX}-someaccount", actor=None)
        assert evil.partition == f"persist:rpa-{PARTITION_PREFIX}-someaccount"
        assert not evil.partition.startswith(f"persist:{PARTITION_PREFIX}-")


def test_run_action_roundtrip_returns_worker_result() -> None:
    _, ws = _workspace()
    worker = worker_client()
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws, actor=None).id

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
        json={
            "action_id": action["id"],
            "status": "done",
            "result": {"value": "Hello"},
            "last_url": "https://x.test/",
            # 认领时拿到的令牌要原样带回(ADR-0002)—— 不带就会被拒,那正是这道闸的作用。
            "lease_token": action["lease_token"],
        },
    )

    t.join(timeout=5)
    assert holder.get("result") == {"value": "Hello"}
    with SessionLocal() as db:
        assert db.get(BrowserSession, sid).last_url == "https://x.test/"  # last_url 落到会话


def test_run_action_failure_propagates() -> None:
    _, ws = _workspace()
    worker = worker_client()
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws, actor=None).id

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
        json={"action_id": action["id"], "status": "failed", "error": "元素未找到", "lease_token": action["lease_token"]},
    )
    t.join(timeout=5)
    assert "元素未找到" in holder.get("error", "")


def test_run_action_rejects_closed_session() -> None:
    _, ws = _workspace()
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws, actor=None).id
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
        sid = browser.open_session(db, workspace_id=ws, actor=None).id
        db.add(BrowserAction(session_id=sid, workspace_id=ws, action="navigate", args={}, status="running"))
        db.commit()

    assert browser.reconcile_browser_state() >= 1
    with SessionLocal() as db:
        assert db.get(BrowserSession, sid).status == "closed"
        acts = db.scalars(select(BrowserAction).where(BrowserAction.session_id == sid)).all()
        assert acts and all(a.status == "failed" for a in acts)


# ---------- ADR-0002:这条通道此前一条都没落 ----------


def test_认领带回租约三件套() -> None:
    """认领要告诉执行器:这次的令牌是什么、什么时候到期。

    此前 `ClaimRequest.worker` 收下了却**一次都没用过**,表上也没有对应的列 —— 于是
    "这个执行器还在吗""这条回报是不是它自己领的那条"在这条通道上都没有答案。
    """
    _, ws = _workspace()
    worker = worker_client()
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws, actor=None).id
        db.add(BrowserAction(session_id=sid, workspace_id=ws, action="wait", args={}, status="queued"))
        db.commit()

    action = _claim(worker)
    assert action["lease_token"] and action["lease_expires_at"]
    with SessionLocal() as db:
        row = db.get(BrowserAction, action["id"])
        assert row.lease_worker == "test"
        assert row.lease_token == action["lease_token"]
        assert row.lease_expires_at is not None


def test_令牌对不上的回报被拒() -> None:
    """一个失联又活过来的执行器,不该把结果写在**新执行器正在干的那一份**上。"""
    _, ws = _workspace()
    worker = worker_client()
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws, actor=None).id
        db.add(BrowserAction(session_id=sid, workspace_id=ws, action="wait", args={}, status="queued"))
        db.commit()

    action = _claim(worker)
    refused = worker.patch(
        "/api/browser/worker/report",
        json={"action_id": action["id"], "status": "done", "result": {"v": 1}, "lease_token": "someone-else"},
    )
    assert refused.status_code == 422
    with SessionLocal() as db:
        assert db.get(BrowserAction, action["id"]).status == "running"  # 没被写坏


def test_心跳续约_续不上的要说出来() -> None:
    """心跳的作用是**带着 claims 来续约**,而不是只说一句"我还在"。

    续不上只有三种可能:不是你领的、令牌不对、已经判过期 —— 三种都不该让那个执行器继续写结果。
    """
    _, ws = _workspace()
    worker = worker_client()
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws, actor=None).id
        db.add(BrowserAction(session_id=sid, workspace_id=ws, action="wait", args={}, status="queued"))
        db.commit()

    action = _claim(worker)
    body = {"worker": "test", "claims": [{"action_id": action["id"], "lease_token": action["lease_token"]}]}
    assert worker.post("/api/browser/worker/heartbeat", json=body).json()["renewed"] == [action["id"]]

    # 换一个身份来续同一条:续不上。
    other = {"worker": "another", "claims": body["claims"]}
    assert worker.post("/api/browser/worker/heartbeat", json=other).json()["renewed"] == []


def test_租约到点的动作判失败_可重试() -> None:
    """执行器崩了/被杀了/网断了 —— 动作不会自己回来,而调用方只会等到一个"执行器未响应"。"""
    from datetime import timedelta

    from app.db.models import now

    _, ws = _workspace()
    worker = worker_client()
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws, actor=None).id
        db.add(BrowserAction(session_id=sid, workspace_id=ws, action="wait", args={}, status="queued"))
        db.commit()

    action = _claim(worker)
    with SessionLocal() as db:
        row = db.get(BrowserAction, action["id"])
        row.lease_expires_at = now() - timedelta(seconds=1)
        db.commit()

    with SessionLocal() as db:
        assert browser.expire_action_leases(db) == 1
        row = db.get(BrowserAction, action["id"])
        assert row.status == "failed"
        #: 后端自己记的原因存文案 key(「key 或一句话」,同 jobs.say),等它的那一方按读者语言翻。
        assert row.error == "browserErr_executorLost"
        assert "租约" in t(row.error, "zh")
