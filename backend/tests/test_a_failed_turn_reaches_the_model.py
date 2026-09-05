"""失败的回合模型没见过 —— 下一轮要如实告诉它。

模型的记忆是 `AgentSession.adapter_state`(pi 序列化的消息),**只有成功的回合会回存它**:
`host._run_turn` 的两条 except 分支写 AgentMessage、记账、标失败,唯独不碰 adapter_state。

于是一失败,两份对话就分叉 —— 界面上用户看得见自己说过的话和那条「执行失败」,模型的记忆
却停在最后一次成功的回合。真机上的样子是用户说「再试一次」,模型答「这句含义不太明确」,
然后照着**上一次成功**那轮的话题往下推:它不是在装傻,它确实不知道中间试过什么。

这条测试钉的是那段补记:丢了什么就说什么,没丢就一个字都不加。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import AgentMessage, AgentSession
from app.domain.agent.host import unseen_since_last_success
from tests.util import fresh_client


def _session(db, workspace_id: str) -> AgentSession:
    row = AgentSession(workspace_id=workspace_id, title="会话")
    db.add(row)
    db.flush()
    return row


def _say(db, session_id: str, role: str, content: str, error: str | None = None) -> None:
    db.add(AgentMessage(session_id=session_id, role=role, content=content, error=error))
    db.flush()


def test_一切顺利时不加任何东西() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        session = _session(db, workspace["id"])
        _say(db, session.id, "user", "把节点换成 k3")
        _say(db, session.id, "assistant", "换好了")
        assert unseen_since_last_success(db, session) == ""


def test_失败那一轮的提问和原因都要补给模型() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        session = _session(db, workspace["id"])
        _say(db, session.id, "user", "把节点换成 k3")
        _say(db, session.id, "assistant", "换好了")  # 这一轮成功 —— 模型记得
        _say(db, session.id, "user", "我想做一个二次元恋爱相关主题的20s左右的视频")
        _say(db, session.id, "assistant", "智能体执行失败,请稍后重试。", error="上游超时")

        note = unseen_since_last_success(db, session)
        # 用户说过的话要在里面 —— 否则「再试一次」指代不到任何东西。
        assert "二次元恋爱" in note
        # 失败原因也要 —— 不然模型会以为那次是自己做完了。
        assert "上游超时" in note
        # 成功那一轮不该重复:模型已经记得它了,再说一遍是在浪费上下文。
        assert "换好了" not in note


def test_连续失败要把丢掉的每一轮都说出来() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        session = _session(db, workspace["id"])
        _say(db, session.id, "user", "第一次请求")
        _say(db, session.id, "assistant", "失败", error="错误甲")
        _say(db, session.id, "user", "第二次请求")
        _say(db, session.id, "assistant", "失败", error="错误乙")

        note = unseen_since_last_success(db, session)
        for fragment in ("第一次请求", "错误甲", "第二次请求", "错误乙"):
            assert fragment in note, fragment


def test_从没成功过也补得出来() -> None:
    """一上来就失败:没有「最后一次成功」这个锚点,不能因此什么都不说。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        session = _session(db, workspace["id"])
        _say(db, session.id, "user", "开场就炸的那一句")
        _say(db, session.id, "assistant", "失败", error="供应商没配")

        note = unseen_since_last_success(db, session)
        assert "开场就炸的那一句" in note and "供应商没配" in note
