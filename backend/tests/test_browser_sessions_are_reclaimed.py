"""智能体开的浏览器会话归**那次对话**,没人关的会话空闲一段时间后自动收回。

此前智能体开会话一律记成 owner ("agent", ""):所有人、所有对话共用同一个具名会话;而智能体用完多半
不发「关闭」,那个具名会话就一直开着 —— 之后任何一次工作流打开同名会话,都报「被占用」,直到后端重启。
工作流进程异常退出遗留的会话也是同一个下场。
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import update

from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import BrowserAction, BrowserSession, Job, User, now
from app.domain import browser
from tests.util import fresh_client, worker_client


def _card(client, ws: str, agent_session_id: str | None, payload: dict) -> dict:
    """以某次对话的身份开一张「打开浏览器」卡并批准它(归属由凭据决定,见 test_confirmations)。"""
    login = client.headers["Authorization"]
    if agent_session_id is not None:
        with SessionLocal() as db:
            user = db.query(User).filter(User.username == "tester").one()
            client.headers["Authorization"] = f"Bearer {mint_service_session(db, user.id, agent_session_id=agent_session_id)}"
    card = client.post("/api/confirmations", json={"workspace_id": ws, "tool": "browser_open", "payload": payload}).json()
    client.headers["Authorization"] = login
    return client.post(f"/api/confirmations/{card['id']}/approve").json()


def _conversation(client, ws: str) -> str:
    return client.post("/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": ws}).json()["id"]


def _age(session_id: str, minutes: int) -> None:
    """把会话(和它的动作)往回拨:最后一次动作是 `minutes` 分钟前。"""
    then = now() - timedelta(minutes=minutes)
    with SessionLocal() as db:
        db.get(BrowserSession, session_id).created_at = then
        for act in db.query(BrowserAction).filter(BrowserAction.session_id == session_id):
            act.updated_at = then
        db.commit()


def _open_wf(ws: str, run: str, name: str = "xhs") -> BrowserSession:
    with SessionLocal() as db:
        return browser.open_session(
            db, workspace_id=ws, kind="named", name=name, owner_kind="workflow", owner_id=run, actor=None
        )


NAMED = {"url": "", "session_mode": "named", "session_name": "xhs"}


def test_智能体开的具名会话归那次对话_别的对话打开同名会话是被占用() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    a, b = _conversation(client, ws), _conversation(client, ws)

    first = _card(client, ws, a, NAMED)
    assert first["status"] == "executed"
    with SessionLocal() as db:
        session = db.get(BrowserSession, first["result"]["session_id"])
        assert (session.owner_kind, session.owner_id) == ("agent", a)

    # 同一次对话再开同名会话:复用
    again = _card(client, ws, a, NAMED)
    assert again["result"]["session_id"] == first["result"]["session_id"]
    # 别的对话:被占用,不是拿到 A 那次对话登录好的视图
    other = _card(client, ws, b, NAMED)
    assert other["status"] != "executed"
    assert "xhs" in (other.get("error") or "")


def test_外部智能体的卡没有对话_会话归这张卡() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    done = _card(client, ws, None, {"url": "", "session_mode": "ephemeral"})
    with SessionLocal() as db:
        session = db.get(BrowserSession, done["result"]["session_id"])
        assert (session.owner_kind, session.owner_id) == ("agent", done["id"])


def test_智能体没关的具名会话空闲过了时限_工作流打开同名会话时收回() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    left = _card(client, ws, _conversation(client, ws), NAMED)["result"]["session_id"]

    # 刚用过:照样被占用
    try:
        _open_wf(ws, "job-1")
        raise AssertionError("还在用的会话被抢走了")
    except browser.BrowserDomainError as exc:
        assert exc.key == "browserErr_sessionBusy"

    _age(left, minutes=16)
    opened = _open_wf(ws, "job-1")
    assert opened.id != left
    with SessionLocal() as db:
        assert db.get(BrowserSession, left).status == "closed"
        # 执行器那边的视图也要拆:排了一条 close
        assert db.query(BrowserAction).filter(
            BrowserAction.session_id == left, BrowserAction.action == "close", BrowserAction.status == "queued"
        ).count() == 1


def test_执行器认领时扫一遍_空着的会话被关掉并领走拆视图那条() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    left = _card(client, ws, _conversation(client, ws), {"url": "", "session_mode": "ephemeral"})["result"]["session_id"]
    _age(left, minutes=30)

    claimed = worker_client().post("/api/browser/worker/claim", json={"worker": "w"}).json()["action"]
    assert claimed is not None and (claimed["action"], claimed["session_id"]) == ("close", left)
    with SessionLocal() as db:
        assert db.get(BrowserSession, left).status == "closed"


def test_还有动作在排的会话不算空闲() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    session = _open_wf(ws, "")
    with SessionLocal() as db:
        db.add(BrowserAction(session_id=session.id, workspace_id=ws, action="wait", args={}, status="running"))
        db.commit()
    _age(session.id, minutes=60)
    with SessionLocal() as db:
        assert browser.reclaim_idle_sessions(db) == 0


def test_工作流的会话_运行还没结束就不收_运行异常退出遗留的才收() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        live = Job(workspace_id=ws, kind="workflow", status="running", payload={})
        gone = Job(workspace_id=ws, kind="workflow", status="running", payload={})
        db.add_all([live, gone])
        db.commit()
        live_id, gone_id = live.id, gone.id
    held = _open_wf(ws, live_id, name="a").id
    leftover = _open_wf(ws, gone_id, name="b").id
    #: 进程异常退出:任务落了终态,而「运行结束就关会话」那一下没跑到(直接改库,不经任务总线的落终态钩子)
    with SessionLocal() as db:
        db.execute(update(Job).where(Job.id == gone_id).values(status="failed"))
        db.commit()
        assert db.get(BrowserSession, leftover).status == "open"
    _age(held, minutes=60)
    _age(leftover, minutes=60)

    with SessionLocal() as db:
        assert browser.reclaim_idle_sessions(db) == 1
        db.commit()
    with SessionLocal() as db:
        assert db.get(BrowserSession, held).status == "open"
        assert db.get(BrowserSession, leftover).status == "closed"


def test_空闲时限可以关掉(monkeypatch) -> None:
    from app.core.config import settings

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    session = _open_wf(ws, "")
    _age(session.id, minutes=600)
    monkeypatch.setattr(settings, "browser_session_idle_minutes", 0)
    with SessionLocal() as db:
        assert browser.reclaim_idle_sessions(db) == 0
