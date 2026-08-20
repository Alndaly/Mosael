from __future__ import annotations

import time

from app.ai.agent import adapters, host
from app.ai.agent.adapters import TurnResult
from app.core.db import SessionLocal
from app.db.models import ProviderProfile
from tests.util import add_provider, fresh_client


def _configured(client):
    """让这个部署有一个可用的对话模型。

    取默认模型没有"随便挑一个"的兜底(见 provider_models.resolve_default) —— "能对话"必须
    被显式配出来,这也正是真实部署里管理员配完连接顺手做的那一步。
    """
    from app.core.db import SessionLocal
    from tests.util import add_provider

    with SessionLocal() as db:
        add_provider(
            db, name="P", vendor="openai-compatible", base_url="http://localhost:1/v1",
            api_key="k", model="m", capability_ids=["chat"],
        )
        db.commit()
    return client


def wait_idle(client, session_id: str, seconds: float = 8) -> str:
    deadline = time.time() + seconds
    status = client.get(f"/api/agent/sessions/{session_id}").json()["status"]
    while time.time() < deadline:
        status = client.get(f"/api/agent/sessions/{session_id}").json()["status"]
        if status != "running":
            return status
        time.sleep(0.05)
    return status

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

    def fake_run_turn(adapter, *, prompt, system_prompt, api_base, token, on_delta=None, **_):
        calls.update(
            adapter=adapter, prompt=prompt, system=system_prompt, token=token
        )
        return TurnResult(text=f"echo: {prompt}")

    monkeypatch.setattr(host, "run_turn", fake_run_turn)

    client = fresh_client()
    _configured(client)
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

    def fake_run_turn(adapter, *, prompt, system_prompt, api_base, token, on_delta=None, **_):
        calls["prompt"] = prompt
        return TurnResult(text=f"echo: {prompt}")

    monkeypatch.setattr(host, "run_turn", fake_run_turn)

    client = fresh_client()
    _configured(client)
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
    _configured(client)
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
    _configured(client)
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
    # 这条**故意不配可用模型** —— 它测的就是那种状态下的报错,所以不能走 _configured。
    # Public settings now reject a missing model. Insert one invalid row directly so the agent's
    # own preflight guard remains covered against corrupted/manual state.
    with SessionLocal() as db:
        add_provider(
            db, name="P", vendor="openai-compatible", base_url="http://localhost:1/v1", api_key="k", enabled=True
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
    _configured(client)
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
    _configured(client)
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
    _configured(client)
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
    _configured(client)
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()
    assert session["analysis_video_mode"] == "auto"  # 默认

    patched = client.patch(f"/api/agent/sessions/{session['id']}", json={"analysis_video_mode": "native"}).json()
    assert patched["analysis_video_mode"] == "native"
    assert client.get(f"/api/agent/sessions/{session['id']}").json()["analysis_video_mode"] == "native"

    # 非法值被拒
    bad = client.patch(f"/api/agent/sessions/{session['id']}", json={"analysis_video_mode": "bogus"})
    assert bad.status_code == 422


def test_思考块在正文开始时结束_不依赖供应商发_thinking_end() -> None:
    """**「思考中…」不能靠供应商宣布结束**。

    有的链路思考完直接开始吐正文,一个 `thinking_end` 都不发,于是那张卡顶着一个永远转不完的
    转圈,底下正文却已经写完了 —— 用户看到的是自相矛盾的两句话。正文开始本身就是确凿证据。
    """
    session_id = "s-thinking"
    host._stream_reset(session_id)
    host._stream_thinking(session_id, {"type": "thinking_delta", "delta": "先想一下"})
    assert host.get_stream_state(session_id)["timeline"][-1] == {
        "type": "thinking",
        "text": "先想一下",
        "done": False,
    }

    host._stream_append(session_id, "正文开始")
    timeline = host.get_stream_state(session_id)["timeline"]
    assert timeline[0]["type"] == "thinking" and timeline[0]["done"] is True
    assert timeline[1] == {"type": "text", "text": "正文开始"}

    # 之后再有思考(工具循环里常见)是**新的一块**,不会续到已结束的那块上
    host._stream_thinking(session_id, {"type": "thinking_delta", "delta": "再想想"})
    timeline = host.get_stream_state(session_id)["timeline"]
    assert timeline[2] == {"type": "thinking", "text": "再想想", "done": False}

    # 调工具同样意味着思考结束
    host._stream_tool_event(session_id, {"type": "tool_start", "toolCallId": "c1", "name": "list_assets", "args": {}})
    timeline = host.get_stream_state(session_id)["timeline"]
    assert timeline[2]["done"] is True
    assert timeline[3]["type"] == "tool"


def test_一轮结束时不会留下思考中() -> None:
    """只思考、没说话的一轮(被取消、或模型只回了思考)也不该留一个转不完的圈。"""
    session_id = "s-thinking-only"
    host._stream_reset(session_id)
    host._stream_thinking(session_id, {"type": "thinking_delta", "delta": "想了但没说"})
    host._stream_finish(session_id, "")
    timeline = host.get_stream_state(session_id)["timeline"]
    assert timeline == [{"type": "thinking", "text": "想了但没说", "done": True}]


def test_子智能体的每一步进时间线_并嵌在父调用名下() -> None:
    """subtool 事件 → 时间线条目。没有它,run_subagent 是一段几十秒的静默 ——
    旧的 onSubagentStep 回调从来没被接线,这次直接换成完整的 start/end 事件流。"""
    from app.ai.agent import host

    session_id = "sub-trace-test"
    host._stream_reset(session_id)
    try:
        host._stream_tool_event(session_id, {
            "type": "subtool", "phase": "start", "parentCallId": "parent-1",
            "toolCallId": "c1", "toolName": "list_assets", "args": {"kind": "video"},
        })
        state = host.get_stream_state(session_id)
        assert state["timeline"][-1]["type"] == "subtool"
        assert state["timeline"][-1]["parent_id"] == "parent-1"
        assert state["timeline"][-1]["tool"]["status"] == "running"

        host._stream_tool_event(session_id, {
            "type": "subtool", "phase": "end", "parentCallId": "parent-1",
            "toolCallId": "c1", "toolName": "list_assets", "result": {"ok": True}, "isError": False,
        })
        state = host.get_stream_state(session_id)
        entry = state["timeline"][-1]
        assert entry["tool"]["status"] == "done"
        assert entry["tool"]["result"] == {"ok": True}
        # 耗时来自 start→end 的真实间隔,不是猜的
        assert isinstance(entry["tool"]["usage"].get("duration_seconds"), float)

        # 失败的一步要标成 error —— 子智能体里的失败不该被压平成"done"
        host._stream_tool_event(session_id, {
            "type": "subtool", "phase": "start", "parentCallId": "parent-1",
            "toolCallId": "c2", "toolName": "fetch_url", "args": {},
        })
        host._stream_tool_event(session_id, {
            "type": "subtool", "phase": "end", "parentCallId": "parent-1",
            "toolCallId": "c2", "toolName": "fetch_url", "result": "boom", "isError": True,
        })
        state = host.get_stream_state(session_id)
        assert state["timeline"][-1]["tool"]["status"] == "error"
    finally:
        host._stream_reset(session_id)


def test_后台子智能体跑完_存档填回发起那张卡() -> None:
    """subagent_result 事件 → run_subagent 卡的 details.subagent。非阻塞派发的卡瞬间
    就 done 了(回执是「已派发」),存档要等子智能体真跑完才回填 —— 丢了这个事件,
    界面上那张卡永远停在「已派发、无档案」。"""
    from app.ai.agent import host

    session_id = "subagent-result-test"
    host._stream_reset(session_id)
    try:
        # 派发:工具卡开卡、立即收卡(dispatched 回执)
        host._stream_tool_event(session_id, {
            "type": "tool_start", "toolCallId": "parent-1", "name": "run_subagent", "args": {"task": "查素材"},
        })
        host._stream_tool_event(session_id, {
            "type": "tool_end", "toolCallId": "parent-1",
            "result": {"content": [], "details": {"subagent_dispatched": True}}, "isError": False,
        })
        # 后台跑完:存档回填,不动原 content/details 里已有的东西
        archive = {"task": "查素材", "steps": 2, "error": None, "trace": [{"type": "text", "text": "结论"}]}
        host._stream_tool_event(session_id, {
            "type": "subagent_result", "parentCallId": "parent-1", "archive": archive,
        })
        state = host.get_stream_state(session_id)
        card = state["timeline"][-1]["tool"]
        assert card["result"]["details"]["subagent"] == archive
        assert card["result"]["details"]["subagent_dispatched"] is True  # 原有标记不被洗掉
        assert card["status"] == "done"
    finally:
        host._stream_reset(session_id)


def test_记账之后prompt快照和水位不被覆盖丢掉(monkeypatch) -> None:
    """真机上最近 300 条消息里 prompt 快照 0 条 —— 写入代码、读取代码单看都对,
    丢在中间:billable 记完账为了把成本写进 usage,把整个 payload 重新赋值成
    {usage, timeline},第一次构造时的 prompt / context / compaction 全被覆盖。
    轨迹里的 SYSTEM / CONTEXT 行因此从来没出现过。"""
    from app.ai.agent import host
    from app.ai.agent.adapters import TurnResult
    from tests.util import fresh_client

    monkeypatch.setattr(
        host, "run_turn",
        lambda *a, **kw: TurnResult(text="好的", context={"tokens": 1200, "window": 128000}),
    )
    client = fresh_client()
    # 部署得先有一个可用的对话模型:解析供应商发生在 run_turn 之前,没配就走错误分支 ——
    # 那条兜底消息的 payload 天生只有 usage,测不到要测的东西。
    from tests.util import add_provider

    with SessionLocal() as db:
        add_provider(
            db, name="P", vendor="openai-compatible", base_url="http://localhost:1/v1",
            api_key="k", model="m", capability_ids=["chat"],
        )
        db.commit()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"workspace_id": ws["id"], "title": "t"}).json()
    client.post(f"/api/agent/sessions/{session['id']}/messages", json={"content": "hi"})
    assert host.wait_for_idle_turns()

    from app.db.models import AgentMessage

    with SessionLocal() as db:
        rows = db.query(AgentMessage).filter_by(session_id=session["id"], role="assistant").all()
        assert len(rows) == 1
        # 先确认这条不是「执行异常」兜底 —— 那条的 payload 天生只有 usage,断言会误导。
        assert rows[0].error is None, rows[0].error
        payload = rows[0].payload or {}
        # 第一轮必有系统提示快照 —— 它是这条轨迹的基线
        assert isinstance(payload.get("prompt"), dict) and payload["prompt"].get("system"), payload.keys()
        # 上下文水位也得活下来(前端进度条读它)
        assert payload.get("context") == {"tokens": 1200, "window": 128000}
        # 记账补写的 usage 仍然在
        assert "usage" in payload


def test_落库时subtool不被丢掉() -> None:
    """流式期间嵌套卡都在,一刷新全没了 —— _timeline_for_payload 只认三种类型,
    subtool 被静默丢弃。真机上第一次派发就撞上:存档在、时间线里却零条子步。"""
    from app.ai.agent.host import _timeline_for_payload

    stream_state = {
        "timeline": [
            {"type": "tool", "tool": {"id": "p1", "name": "run_subagent", "status": "done"}},
            {"type": "subtool", "parent_id": "p1", "tool": {"id": "c1", "name": "list_assets", "status": "done"}},
            {"type": "text", "text": "结论"},
        ]
    }
    timeline = _timeline_for_payload(stream_state, "结论")
    kinds = [item["type"] for item in timeline]
    assert kinds == ["tool", "subtool", "text"], kinds
    assert timeline[1]["parent_id"] == "p1"
