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


def test_失败带回来的记忆要存下来() -> None:
    """pi 的一轮**跑完了**才带 errorMessage —— 失败点之前的工具调用是真发生过的。

    不回存的话记忆回滚到上一次成功,模型下次醒来不知道自己已经建过项目、改过时间线,
    于是会再做一遍。这是比「不知道失败过」更贵的那个后果。
    """
    from app.ai.sidecar.pi_client import SidecarError

    error = SidecarError("上游 5xx", [{"role": "assistant", "content": "我已经建好项目了"}])
    assert error.adapter_state == [{"role": "assistant", "content": "我已经建好项目了"}]

    # 拿不到就是 None —— sidecar 整个进程没了的那种,确实无从补起。
    assert SidecarError("进程没了").adapter_state is None


def test_sidecar_在错误事件里带上记忆() -> None:
    """协议这一侧:sidecar 手里有 sessionState,失败时也要交出来。

    此前 index.ts 在 result.errorMessage 时只发一个 error 事件就 return,那份记忆连线都没上。
    """
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "agent-sidecar" / "src" / "index.ts").read_text()
    error_send = source.split('message: result.errorMessage', 1)
    assert len(error_send) == 2, "错误事件的发送点变了,这条测试要跟着改"
    error_payload = error_send[1][:700]
    assert "sessionState: result.sessionState" in error_payload, "错误事件没有带上 sessionState"
    assert "usage: result.usage" in error_payload, "错误事件没有带上真实用量"
    assert "context: result.context" in error_payload, "错误事件没有带上上下文水位"


def _say_failed(db, session_id: str, content: str, error: str, *, memory_saved: bool) -> None:
    db.add(AgentMessage(
        session_id=session_id, role="assistant", content=content, error=error,
        payload={"memory_saved": True} if memory_saved else {},
    ))
    db.flush()


def test_记忆已经回存的失败轮不再整段重述_只补那一句中断原因() -> None:
    """失败时 sidecar 交回了记忆(host 回存、落库记 `memory_saved`):那条用户消息和做过的工具调用都在模型记忆里。
    此前这里仍把它们当成「你没见过的」整段重述 —— 同一个请求在模型眼前出现两次,还被告知从没处理过,它会把已经做成的
    部分再做一遍(假模型实测:sleep / create_workflow 又调了一遍)。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        session = _session(db, workspace["id"])
        _say(db, session.id, "user", "帮我建一个叫「出海」的工作流再跑一遍")
        _say_failed(db, session.id, "智能体运行超过 600 秒", error="上游断线", memory_saved=True)

        note = unseen_since_last_success(db, session)
        assert "出海" not in note, "记忆里已经有这句了,不该再重述"
        assert "没有见过" not in note
        assert "上游断线" in note, "它没见过的只有「那一轮失败了、为什么」—— 这一句要补"
        assert "不要把做成的再做一遍" in note


def test_回存过的失败之后又有一轮没回存的_只重述后面那一轮() -> None:
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        session = _session(db, workspace["id"])
        _say(db, session.id, "user", "第一件事")
        _say_failed(db, session.id, "失败", error="错误甲", memory_saved=True)
        _say(db, session.id, "user", "第二件事")
        _say_failed(db, session.id, "失败", error="错误乙", memory_saved=False)

        note = unseen_since_last_success(db, session)
        assert "第一件事" not in note
        assert "第二件事" in note and "错误乙" in note


def test_没回存过的失败之后跟一轮回存过的_前面那段已经随那一轮的提示进了记忆() -> None:
    """后一轮的提示里已经带着前面那段补记(发出去的就是它),它的记忆回存了,前面那段也就在记忆里了。"""
    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        session = _session(db, workspace["id"])
        _say(db, session.id, "user", "第一件事")
        _say_failed(db, session.id, "失败", error="错误甲", memory_saved=False)
        _say(db, session.id, "user", "再试一次")
        _say_failed(db, session.id, "失败", error="错误乙", memory_saved=True)

        note = unseen_since_last_success(db, session)
        assert "第一件事" not in note and "错误甲" not in note
        assert "错误乙" in note
