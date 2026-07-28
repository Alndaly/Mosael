from __future__ import annotations

import time

from app.ai.agent import adapters, host
from app.ai.agent.adapters import TurnResult, build_claude_command, open_studio_mcp_config
from app.core.db import SessionLocal
from app.db.models import ProviderProfile
from tests.util import fresh_client


def wait_idle(client, session_id: str, seconds: float = 8) -> str:
    deadline = time.time() + seconds
    status = client.get(f"/api/agent/sessions/{session_id}").json()["status"]
    while time.time() < deadline:
        status = client.get(f"/api/agent/sessions/{session_id}").json()["status"]
        if status != "running":
            return status
        time.sleep(0.05)
    return status


def test_claude_command_and_mcp_config_shape() -> None:
    config = open_studio_mcp_config("http://127.0.0.1:8800", "tok123")
    server = config["mcpServers"]["open-studio"]
    assert server["env"]["OPEN_STUDIO_TOKEN"] == "tok123"
    assert server["args"][0].endswith("mcp_server.py")

    command = build_claude_command("hi", "sys", "/tmp/cfg.json", "sess-1")
    assert "--resume" in command and "sess-1" in command
    assert "mcp__open-studio" in command  # 必须与 mcpServers 的键一致,否则白名单匹配不到任何工具
    assert command[command.index("--mcp-config") + 1] == "/tmp/cfg.json"


def test_system_prompt_separates_workflow_edits_from_timeline_edits() -> None:
    """The workflow side panel asks the same general agent to edit a graph. The global
    prompt must not steer node deletion into the video timeline tool."""
    prompt = host.SYSTEM_PROMPT_TEMPLATE
    assert "edit_workflow" in prompt
    assert "remove_node" in prompt
    assert "edit_timeline 只用于视频时间线" in prompt
    assert "start/开始节点也可以删除" in prompt
    assert "confirmation_id/status=pending" in prompt


def test_turn_metering_estimates_tokens_when_adapter_usage_is_missing() -> None:
    units = host._turn_metering("请分析这些素材", "可以,我先查看素材列表。", None)
    assert units["requests"] == 1
    assert units["input_characters"] > 0
    assert units["output_characters"] > 0
    assert units["input_tokens"] > 0
    assert units["output_tokens"] > 0
    assert units["total_tokens"] == units["input_tokens"] + units["output_tokens"]
    assert units["token_estimate"] is True


def test_stream_timeline_preserves_text_tool_text_order() -> None:
    session_id = "timeline-order-test"
    host._stream_reset(session_id)
    host._stream_append(session_id, "先说明。")
    host._stream_tool_event(
        session_id,
        {"type": "tool_start", "toolCallId": "tool-1", "name": "list_workflows", "args": {"workspace_id": "w"}},
    )
    host._stream_tool_event(
        session_id,
        {"type": "tool_end", "toolCallId": "tool-1", "result": [{"name": "新工作流"}], "isError": False},
    )
    host._stream_append(session_id, "再总结。")

    state = host.get_stream_state(session_id)

    assert [item["type"] for item in state["timeline"]] == ["text", "tool", "text"]
    assert state["timeline"][0]["text"] == "先说明。"
    assert state["timeline"][1]["tool"]["name"] == "list_workflows"
    assert state["timeline"][1]["tool"]["status"] == "done"
    assert state["timeline"][1]["tool"]["usage"]["duration_seconds"] >= 0
    assert state["timeline"][2]["text"] == "再总结。"


def test_session_turn_lifecycle_with_fake_adapter(monkeypatch) -> None:
    calls: dict = {}

    def fake_run_turn(adapter, *, prompt, system_prompt, api_base, token, adapter_session_id, on_delta=None, **_):
        calls.update(
            adapter=adapter, prompt=prompt, system=system_prompt, token=token, prev=adapter_session_id
        )
        return TurnResult(text=f"echo: {prompt}", adapter_session_id="cli-sess-9")

    monkeypatch.setattr(host, "run_turn", fake_run_turn)

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()
    assert session["status"] == "idle"

    message = client.post(f"/api/agent/sessions/{session['id']}/messages", json={"content": "帮我看看时间线"})
    assert message.status_code == 200

    deadline = time.time() + 10
    messages = []
    while time.time() < deadline:
        messages = client.get(f"/api/agent/sessions/{session['id']}/messages").json()
        if len(messages) >= 2:
            break
        time.sleep(0.1)
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "echo: 帮我看看时间线"
    assert messages[1]["payload"]["usage"]["duration_seconds"] >= 0

    refreshed = client.get(f"/api/agent/sessions/{session['id']}").json()
    assert refreshed["status"] == "idle"
    assert refreshed["title"] == "帮我看看时间线"
    assert calls["prompt"] == "帮我看看时间线"
    assert ws["id"] in calls["system"]
    assert calls["token"]  # service token minted for MCP access


def test_message_context_is_sent_to_agent_but_not_stored_in_transcript(monkeypatch) -> None:
    calls: dict = {}

    def fake_run_turn(adapter, *, prompt, system_prompt, api_base, token, adapter_session_id, on_delta=None, **_):
        calls["prompt"] = prompt
        return TurnResult(text=f"echo: {prompt}")

    monkeypatch.setattr(host, "run_turn", fake_run_turn)

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()
    res = client.post(
        f"/api/agent/sessions/{session['id']}/messages",
        json={"content": "删掉这个节点", "context": "当前工作流 workflow_id=w1"},
    )
    assert res.status_code == 200
    assert res.json()["content"] == "删掉这个节点"

    deadline = time.time() + 10
    messages = []
    while time.time() < deadline:
        messages = client.get(f"/api/agent/sessions/{session['id']}/messages").json()
        if len(messages) >= 2:
            break
        time.sleep(0.1)
    assert messages[0]["content"] == "删掉这个节点"
    assert "workflow_id=w1" not in messages[0]["content"]
    assert calls["prompt"] == "当前工作流 workflow_id=w1\n\n用户消息:\n删掉这个节点"
    assert messages[1]["content"] == f"echo: {calls['prompt']}"


def test_turn_error_becomes_assistant_error_message(monkeypatch) -> None:
    def failing_run_turn(*args, **kwargs):
        raise adapters.AdapterError("boom --api-key sk-secret")

    monkeypatch.setattr(host, "run_turn", failing_run_turn)

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()
    client.post(f"/api/agent/sessions/{session['id']}/messages", json={"content": "hi"})

    deadline = time.time() + 10
    messages = []
    while time.time() < deadline:
        messages = client.get(f"/api/agent/sessions/{session['id']}/messages").json()
        if len(messages) >= 2:
            break
        time.sleep(0.1)
    assert messages[1]["error"]
    assert client.get(f"/api/agent/sessions/{session['id']}").json()["status"] == "idle"


def test_empty_turn_surfaces_error_not_blank_bubble(monkeypatch) -> None:
    """供应商配错时模型返回空 —— 必须报错,不能写一条空消息(界面上看着像什么都没发生)。"""

    def empty_run_turn(*args, **kwargs):
        return TurnResult(text="")

    monkeypatch.setattr(host, "run_turn", empty_run_turn)

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()
    client.post(f"/api/agent/sessions/{session['id']}/messages", json={"content": "hi"})

    deadline = time.time() + 10
    messages = []
    while time.time() < deadline:
        messages = client.get(f"/api/agent/sessions/{session['id']}/messages").json()
        if len(messages) >= 2:
            break
        time.sleep(0.1)
    assert len(messages) >= 2, messages
    reply = messages[1]
    assert reply["content"].strip(), "空回复不能落成空气泡"
    assert reply["error"], "必须带上错误详情"
    assert "供应商" in reply["error"] or "base_url" in reply["error"]
    assert client.get(f"/api/agent/sessions/{session['id']}").json()["status"] == "idle"


def test_missing_model_fails_fast_with_clear_error(monkeypatch) -> None:
    """供应商存在但没有可用模型 —— 开跑前就要报错,而不是把 model="" 丢给 sidecar。"""
    called = {"ran": False}

    def should_not_run(*args, **kwargs):
        called["ran"] = True
        return TurnResult(text="should not get here")

    monkeypatch.setattr(host, "run_turn", should_not_run)

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    # Public settings now reject a missing model. Insert one invalid row directly so the agent's
    # own preflight guard remains covered against corrupted/manual state.
    with SessionLocal() as db:
        db.add(
            ProviderProfile(
                name="P",
                vendor="openai-compatible",
                base_url="http://localhost:1/v1",
                api_key="k",
                default_model="",
                enabled=True,
            )
        )
        db.commit()
    session = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()
    client.post(f"/api/agent/sessions/{session['id']}/messages", json={"content": "hi"})

    deadline = time.time() + 10
    messages = []
    while time.time() < deadline:
        messages = client.get(f"/api/agent/sessions/{session['id']}/messages").json()
        if len(messages) >= 2:
            break
        time.sleep(0.1)
    assert len(messages) >= 2, messages
    # 必须是「没有可用的模型」,而不是「未配置可用的 AI 供应商」——否则说明供应商压根没建成,
    # 这条用例就没真正覆盖到新加的模型预检。
    assert "模型" in messages[1]["error"], messages[1]["error"]
    assert called["ran"] is False, "不该真的去跑 sidecar"


def test_a_message_sent_mid_turn_is_accepted_and_queued(monkeypatch) -> None:
    """It used to answer 409, which made the user wait out work they were already correcting.

    It is queued rather than steered: it waits for the running reason-act loop to finish and
    then gets a turn of its own. Steering — cutting into the loop — is a separate, opt-in
    action on the queued item. See test_agent_queue.py for both halves.
    """
    steers: list[str] = []

    def slow_run_turn(*args, **kwargs):
        time.sleep(1.5)
        return TurnResult(text="ok")

    monkeypatch.setattr(host, "run_turn", slow_run_turn)
    monkeypatch.setattr(host, "steer_turn", lambda sid, text, mode="steer": steers.append(text) or True)

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()
    assert client.post(f"/api/agent/sessions/{session['id']}/messages", json={"content": "one"}).status_code == 200

    second = client.post(f"/api/agent/sessions/{session['id']}/messages", json={"content": "two"})

    assert second.status_code == 200, second.text
    assert steers == [], "a plain follow-up must not cut into the running turn"
    assert [m["content"] for m in client.get(f"/api/agent/sessions/{session['id']}/queue").json()] == ["two"]
    assert wait_idle(client, session["id"]) == "idle"


def test_stop_is_not_an_error_when_nothing_is_running() -> None:
    """The user pressing stop as a turn ends is a race they cannot see."""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()

    res = client.post(f"/api/agent/sessions/{session['id']}/stop")

    assert res.status_code == 200
    assert res.json() == {"stopped": False}


def test_reconcile_orphaned_agent_sessions() -> None:
    """重启把 running 会话线程杀死 → 启动时拨回 idle 并补中断说明,idle 会话不动。"""
    from app.ai.agent.host import reconcile_orphaned_agent_sessions
    from app.db.models import AgentMessage, AgentSession
    from app.core.db import SessionLocal

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        stuck = AgentSession(workspace_id=ws["id"], title="卡住的", status="running")
        fine = AgentSession(workspace_id=ws["id"], title="好好的", status="idle")
        db.add_all([stuck, fine])
        db.commit()
        stuck_id, fine_id = stuck.id, fine.id

        assert reconcile_orphaned_agent_sessions(db) == 1

        db.refresh(stuck)
        db.refresh(fine)
        assert stuck.status == "idle"
        assert fine.status == "idle"
        from sqlalchemy import select
        notes = db.scalars(select(AgentMessage).where(AgentMessage.session_id == stuck_id)).all()
        assert len(notes) == 1 and "中断" in notes[0].content and notes[0].error
        assert db.scalars(select(AgentMessage).where(AgentMessage.session_id == fine_id)).all() == []

        # 幂等
        assert reconcile_orphaned_agent_sessions(db) == 0


def test_session_analysis_video_mode_patch() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()
    assert session["analysis_video_mode"] == "auto"  # 默认

    patched = client.patch(f"/api/agent/sessions/{session['id']}", json={"analysis_video_mode": "native"}).json()
    assert patched["analysis_video_mode"] == "native"
    assert client.get(f"/api/agent/sessions/{session['id']}").json()["analysis_video_mode"] == "native"

    # 非法值被拒
    bad = client.patch(f"/api/agent/sessions/{session['id']}", json={"analysis_video_mode": "bogus"})
    assert bad.status_code == 422
