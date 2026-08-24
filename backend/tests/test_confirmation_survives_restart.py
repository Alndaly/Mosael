"""后端重启之后,上一轮留下的确认卡不能还能点。

真机场景:后端 --reload 重启,对话上方如实写着「上一轮对话因后端重启而中断,请重新发送」,
而下方那张确认卡还亮着「允许一次 / 本会话始终允许 / 拒绝」三个按钮。

这不是"点了没反应"那种小事。approve_confirmation 是**当场执行工具**的 —— 它不是唤醒某个
还在等待的线程,而是自己把动作做掉。所以点那张卡会真的把浏览器打开、把节点加上、把钱花掉,
而结果没有任何一轮对话去接收:一个已经没有上下文的动作,仍然可以被执行。

作废只针对**有会话的那批**。session_id 为空的卡来自 MCP / 飞书等外部智能体,那是另一条
生命周期(对方进程可能还活着、还在等人点),顺手清掉它们是另一个 bug。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import AgentSession, ToolConfirmation
from tests.util import fresh_client


def _pending(db, **extra) -> ToolConfirmation:
    row = ToolConfirmation(status="pending", tool="browser_open", permission="external", summary="打开浏览器", **extra)
    db.add(row)
    return row


def test_重启把中断那轮的确认卡一并作废() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    sid = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()["id"]

    with SessionLocal() as db:
        db.get(AgentSession, sid).status = "running"          # 重启前正跑着
        _pending(db, workspace_id=ws["id"], session_id=sid)
        db.commit()

    from app.domain.agent.host import reconcile_orphaned_agent_sessions

    with SessionLocal() as db:
        assert reconcile_orphaned_agent_sessions(db) == 1

    with SessionLocal() as db:
        card = db.scalars(select_cards(sid)).one()
        assert card.status == "cancelled", f"中断那轮的卡还是 {card.status} —— 点下去会真的执行"
        assert card.resolved_at is not None

    # 界面据此不再显示它:内联卡只拉 status=pending。
    listed = client.get(f"/api/confirmations?workspace_id={ws['id']}&status=pending&session_id={sid}").json()
    assert listed == [], "作废之后界面上还挂着"


def test_外部智能体的卡不受牵连() -> None:
    """session_id 为空 = MCP / 飞书那条路,对方进程可能还活着。"""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    sid = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()["id"]

    with SessionLocal() as db:
        db.get(AgentSession, sid).status = "running"
        _pending(db, workspace_id=ws["id"], session_id=None)
        db.commit()

    from app.domain.agent.host import reconcile_orphaned_agent_sessions

    with SessionLocal() as db:
        reconcile_orphaned_agent_sessions(db)

    with SessionLocal() as db:
        card = db.scalars(select_cards(None)).one()
        assert card.status == "pending", "把外部智能体还在等的卡也清掉了"


def test_没有卡在跑的时候什么都不动() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    sid = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()["id"]

    with SessionLocal() as db:
        _pending(db, workspace_id=ws["id"], session_id=sid)   # 会话是 idle,这张卡是本轮的
        db.commit()

    from app.domain.agent.host import reconcile_orphaned_agent_sessions

    with SessionLocal() as db:
        assert reconcile_orphaned_agent_sessions(db) == 0

    with SessionLocal() as db:
        assert db.scalars(select_cards(sid)).one().status == "pending", "把还有效的卡也作废了"


def select_cards(session_id):
    from sqlalchemy import select

    return select(ToolConfirmation).where(ToolConfirmation.session_id.is_(None) if session_id is None
                                          else ToolConfirmation.session_id == session_id)
