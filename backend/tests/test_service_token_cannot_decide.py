"""交给 sidecar 的服务令牌,批不了确认卡、答不了选择卡(智能体那一路 AGENT-14)。

服务令牌此前只按路径前缀放行:`/api/confirmations` 这一组放给它,是因为 sidecar 要轮询卡的结果 —— 可同一份令牌
POST `/api/confirmations/{id}/approve` 也过。拿到这份令牌的进程(sidecar、它起的子进程)就能替用户批它自己开的卡,
而那正是确认卡整套机制里最不该给出去的一项。现在那几组路由上只许读;写只有调工具、开卡(提议)、作废等到点的卡、回写自己的凭据。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.core.security import mint_service_session, service_request_allowed
from app.db.models import AgentSession, AgentQuestion, ToolConfirmation
from tests.test_agent_queue import _session
from tests.util import fresh_client, user_id


def _card(session_id: str) -> str:
    with SessionLocal() as db:
        session = db.get(AgentSession, session_id)
        card = ToolConfirmation(workspace_id=session.workspace_id, tool="create_workflow", permission="edit",
                                summary="新建工作流", payload={"name": "x"}, session_id=session_id, requested_by="pi-agent")
        db.add(card)
        db.commit()
        return card.id


def test_服务令牌读得到卡_批不了也拒不了() -> None:
    client = fresh_client()
    sid = _session(client)
    card = _card(sid)
    with SessionLocal() as db:
        service = {"Authorization": f"Bearer {mint_service_session(db, user_id(), agent_session_id=sid)}"}

    assert client.get(f"/api/confirmations/{card}", headers=service).status_code == 200, "sidecar 要轮询卡的结果"
    assert client.post(f"/api/confirmations/{card}/approve", headers=service).status_code == 403
    assert client.post(f"/api/confirmations/{card}/reject", headers=service).status_code == 403
    with SessionLocal() as db:
        assert db.get(ToolConfirmation, card).status == "pending"
    # 卡等到点由那一轮自己作废:这一条写放行。
    assert client.post(f"/api/confirmations/{card}/expire", headers=service).status_code == 200
    # 登录令牌(人)照旧能批 / 拒 —— 换一张新卡试。
    other = _card(sid)
    assert client.post(f"/api/confirmations/{other}/approve").status_code != 403


def test_服务令牌答不了选择卡() -> None:
    client = fresh_client()
    sid = _session(client)
    with SessionLocal() as db:
        session = db.get(AgentSession, sid)
        question = AgentQuestion(workspace_id=session.workspace_id, session_id=sid,
                                 questions=[{"question": "走哪条", "options": [{"label": "甲"}, {"label": "乙"}]}])
        db.add(question)
        db.commit()
        qid = question.id
        service = {"Authorization": f"Bearer {mint_service_session(db, user_id(), agent_session_id=sid)}"}
    assert client.get(f"/api/agent/questions/{qid}", headers=service).status_code == 200
    assert client.post(f"/api/agent/questions/{qid}/answer", json={"answers": {"走哪条": "甲"}}, headers=service).status_code == 403
    assert client.post(f"/api/agent/questions/{qid}/dismiss", headers=service).status_code == 403


def test_放行的写只有那几条() -> None:
    allowed = [
        ("POST", "/api/agent/tools/create_workflow"),
        ("POST", "/api/confirmations/c1/expire"),
        ("POST", "/api/confirmations"),  # 开卡是提议:挂在这份令牌那一轮上,批不批照样是人
        ("POST", "/api/agent/provider-credentials/p1/acquire"),
        ("POST", "/api/agent/provider-credentials/p1/commit"),
        ("POST", "/api/agent/provider-credentials/p1/renew"),
        ("POST", "/api/agent/provider-credentials/p1/release"),
        ("GET", "/api/agent/tools"),
        ("GET", "/api/confirmations/c1"),
        ("GET", "/api/agent/questions/q1"),
    ]
    denied = [
        ("POST", "/api/confirmations/c1/approve"),
        ("POST", "/api/confirmations/c1/reject"),
        ("POST", "/api/confirmations/c1/answer"),
        ("POST", "/api/agent/questions/q1/answer"),
        ("POST", "/api/agent/questions/q1/dismiss"),
        ("GET", "/api/workspaces"),
        ("POST", "/api/agent/sessions"),
    ]
    for method, path in allowed:
        assert service_request_allowed(method, path), f"{method} {path} 应当放行"
    for method, path in denied:
        assert not service_request_allowed(method, path), f"{method} {path} 不该放行"
