"""一轮中途断掉时,**模型已经说过的话要留在库里**。

维护者:「任务一旦中断或者失败,过去智能体发给我的所有消息都没了,仅剩下工具调用历史,这是不对的」。

根因不在界面:助手消息此前只在"跑完"那一刻写一次,正文全程只在内存的 `_streams` 里 ——
后端重启 / 进程被杀 / 一轮失败时,那些字**根本没落过库**,界面自然什么都画不出来。
现在一轮开始时先落一条草稿,流式过程中节流写正文;失败或重启接管时**更新那条草稿**,
把中断说明接在后面,而不是另起一条空消息把正文盖掉。
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from tests.util import fresh_client


def _wait(client: TestClient, session_id: str) -> list[dict]:
    deadline = time.time() + 30
    messages: list[dict] = []
    while time.time() < deadline:
        messages = client.get(f"/api/agent/sessions/{session_id}/messages").json()
        if len(messages) >= 2 and not (messages[-1].get("payload") or {}).get("streaming"):
            return messages
        time.sleep(0.05)
    return messages


def test_a_failed_turn_keeps_what_the_model_already_said(monkeypatch) -> None:
    from app.domain.agent import host

    def failing_run_turn(adapter, *, on_delta, **_kwargs):
        #: 先说两句,再从中间炸掉 —— 这两句必须留下来。
        on_delta("我先看看节点类型。")
        on_delta("搭好了 4 路并发抓取。")
        raise host.SidecarError("agentErr_turnFailed", human="智能体执行失败，请稍后重试。")

    monkeypatch.setattr(host, "run_turn", failing_run_turn)
    client = fresh_client()
    # 这个部署得有一个能对话的模型 —— 复用 test_agent_host 的同一个配置步骤,不重写一份。
    from tests.test_agent_host import _configured

    _configured(client)
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": ws["id"]}).json()
    client.post(f"/api/agent/sessions/{session['id']}/messages", json={"content": "搭个工作流"})

    messages = _wait(client, session["id"])
    assistant = messages[-1]
    assert assistant["role"] == "assistant"
    # 说过的话还在,失败原因接在后面(而不是只剩一句"执行失败")。
    assert "我先看看节点类型。" in assistant["content"]
    assert "搭好了 4 路并发抓取。" in assistant["content"]
    assert "智能体执行失败" in assistant["content"]
    # 草稿只应该有一条:收尾是**更新**它,不是另起一条。
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert not (assistant.get("payload") or {}).get("streaming"), "收尾后不该还挂着 streaming"


def test_a_restart_keeps_the_draft_text_and_appends_the_notice() -> None:
    """后端重启接管一个卡在 running 的会话:草稿里已经流出来的字**留着**,中断说明接在后面。"""
    from app.core.db import SessionLocal
    from app.db.models import AgentMessage, AgentSession
    from app.domain.agent.host import INTERRUPTED_NOTICE, reconcile_orphaned_agent_sessions

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"home": {"kind": "studio"}, "workspace_id": ws["id"]}).json()

    with SessionLocal() as db:
        row = db.get(AgentSession, session["id"])
        row.status = "running"
        draft = AgentMessage(
            session_id=session["id"],
            role="assistant",
            content="我已经读完 15 个节点。",
            payload={"streaming": True},
        )
        db.add(draft)
        db.commit()
        draft_id = draft.id

        #: 重启接管(启动时跑一次)。
        reconcile_orphaned_agent_sessions(db)
        db.commit()

        kept = db.get(AgentMessage, draft_id)
        assert kept is not None, "不该另起一条:草稿就是这一轮的那条消息"
        assert "我已经读完 15 个节点。" in kept.content, "已经说过的话不能丢"
        assert INTERRUPTED_NOTICE in kept.content, "中断说明要接在后面"
        assert kept.error == "backend restarted mid-turn"
        assert not (kept.payload or {}).get("streaming"), "接管之后不再是流式中"

        # 会话里只有这一条助手消息 —— 没有多出来的空消息。
        roles = [m.role for m in db.query(AgentMessage).filter(AgentMessage.session_id == session["id"]).all()]
        assert roles.count("assistant") == 1
