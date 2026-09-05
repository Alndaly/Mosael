"""答完选择卡要有下文 —— 否则点完就什么都不发生。

`ask_user` 不阻塞:模型建完问题拿回一个 id,轮询一次多半还是 pending,然后这一轮就结束了
(它没有别的办法等下去)。用户随后在界面上选 —— 而「选」原本只是把一行状态改成 answered,
没有任何东西会再开一轮。真机上撞到的就是这个:选完之后界面毫无反应,模型也再没醒过来。

`dismiss` 的说明一直写着「模型会收到『用户跳过了』并继续往下走」。回合都结束了,它拿什么收到 ——
这句话要成立,就得有人把结果送回去。送法照任务回执那条现成的路(domain/agent/receipts):
会话闲就开新一轮,忙就排队。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import AgentMessage, AgentQuestion, AgentSession
from tests.util import fresh_client

QUESTIONS = [
    {
        "header": "题材",
        "question": "成片走哪个方向?",
        "options": [{"label": "告白场景", "description": "甜"}, {"label": "失恋与救赎", "description": "苦"}],
    }
]


def _ask(client, workspace_id: str) -> tuple[str, str]:
    """建一个会话和一张待答的选择卡,返回 (session_id, question_id)。"""
    with SessionLocal() as db:
        session = AgentSession(workspace_id=workspace_id, title="会话")
        db.add(session)
        db.commit()
        session_id = session.id
    created = client.post(
        "/api/agent/questions",
        json={"workspace_id": workspace_id, "session_id": session_id, "questions": QUESTIONS},
    )
    assert created.status_code in (200, 201), created.text
    return session_id, created.json()["id"]


def _user_messages(session_id: str) -> list[str]:
    with SessionLocal() as db:
        rows = db.query(AgentMessage).filter(AgentMessage.session_id == session_id).all()
        return [row.content for row in rows if row.role == "user"]


def test_答完之后会话里多出一条用户消息() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    session_id, question_id = _ask(client, workspace["id"])
    assert _user_messages(session_id) == [], "还没答,不该有任何东西"

    answered = client.post(
        f"/api/agent/questions/{question_id}/answer",
        json={"answers": {"成片走哪个方向?": ["告白场景"]}},
    )
    assert answered.status_code == 200, answered.text

    said = _user_messages(session_id)
    assert len(said) == 1, f"答完了却没有下文:{said}"
    # 选了什么要在正文里 —— 模型下一轮就靠这句话知道走哪条路。
    assert "告白场景" in said[0]


def test_跳过也要有下文() -> None:
    """dismiss 的说明承诺「模型会收到『用户跳过了』」—— 那就得真的收得到。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    session_id, question_id = _ask(client, workspace["id"])

    skipped = client.post(f"/api/agent/questions/{question_id}/dismiss")
    assert skipped.status_code == 200, skipped.text

    said = _user_messages(session_id)
    assert len(said) == 1 and "跳过" in said[0], said


def test_答案本身仍然记在那一行上() -> None:
    """送回对话是**额外**的一步,不能因此丢了 get_answer 那条路 —— 两个消费者都要有。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    _, question_id = _ask(client, workspace["id"])

    client.post(
        f"/api/agent/questions/{question_id}/answer",
        json={"answers": {"成片走哪个方向?": ["失恋与救赎"]}},
    )
    row = client.get(f"/api/agent/questions/{question_id}").json()
    assert row["status"] == "answered"
    assert "失恋与救赎" in str(row["answers"])


def test_重复回答仍然被拒() -> None:
    """新增的送达不能把「已经答过了」这道校验绕过去。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    session_id, question_id = _ask(client, workspace["id"])

    body = {"answers": {"成片走哪个方向?": ["告白场景"]}}
    assert client.post(f"/api/agent/questions/{question_id}/answer", json=body).status_code == 200
    assert client.post(f"/api/agent/questions/{question_id}/answer", json=body).status_code == 422
    # 被拒的那次不该也送一条 —— 否则会话里会多出一条根本没发生的选择。
    assert len(_user_messages(session_id)) == 1


def test_会话没了不炸() -> None:
    """会话被删掉之后再答一次:送不出去是正常结果,不是 500。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    session_id, question_id = _ask(client, workspace["id"])
    with SessionLocal() as db:
        db.query(AgentQuestion).filter(AgentQuestion.id == question_id).update({"session_id": "没有这个会话"})
        db.commit()

    answered = client.post(
        f"/api/agent/questions/{question_id}/answer",
        json={"answers": {"成片走哪个方向?": ["告白场景"]}},
    )
    assert answered.status_code == 200, answered.text
    assert _user_messages(session_id) == []
