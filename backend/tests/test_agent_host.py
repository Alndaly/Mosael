from __future__ import annotations

import time

from app.ai.agent import adapters, host
from app.ai.agent.adapters import TurnResult, build_claude_command, mibu_mcp_config
from tests.util import fresh_client


def test_claude_command_and_mcp_config_shape() -> None:
    config = mibu_mcp_config("http://127.0.0.1:8800", "tok123")
    server = config["mcpServers"]["mibu"]
    assert server["env"]["MIBU_TOKEN"] == "tok123"
    assert server["args"][0].endswith("mcp_server.py")

    command = build_claude_command("hi", "sys", "/tmp/cfg.json", "sess-1")
    assert "--resume" in command and "sess-1" in command
    assert "mcp__mibu" in command
    assert command[command.index("--mcp-config") + 1] == "/tmp/cfg.json"


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

    refreshed = client.get(f"/api/agent/sessions/{session['id']}").json()
    assert refreshed["status"] == "idle"
    assert refreshed["title"] == "帮我看看时间线"
    assert calls["prompt"] == "帮我看看时间线"
    assert ws["id"] in calls["system"]
    assert calls["token"]  # service token minted for MCP access


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
    # 启用一个没有 default_model 的供应商
    client.post(
        "/api/settings/providers",
        json={"name": "P", "vendor": "openai-compatible", "base_url": "http://localhost:1/v1", "api_key": "k", "default_model": "", "enabled": True},
    )
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


def test_stop_is_not_an_error_when_nothing_is_running() -> None:
    """The user pressing stop as a turn ends is a race they cannot see."""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()

    res = client.post(f"/api/agent/sessions/{session['id']}/stop")

    assert res.status_code == 200
    assert res.json() == {"stopped": False}


def test_prompt_skills_seed_list_and_load(tmp_path, monkeypatch) -> None:
    from app.core.config import settings
    from app.domain.agent import prompt_skills

    monkeypatch.setattr(settings, "data_dir", tmp_path)
    client = fresh_client()

    listed = client.get("/api/agent/prompt-skills").json()
    ids = {skill["id"] for skill in listed}
    assert "transcript-rough-cut" in ids and "export-delivery" in ids
    assert all(skill.get("body") in (None, "") for skill in listed)  # 列表不带正文

    loaded = client.get("/api/agent/prompt-skills/transcript-rough-cut").json()
    assert loaded["name"] == "逐字稿粗剪"
    assert "cut_clip_ranges" in loaded["body"]

    # 用户自建技能:目录 + SKILL.md 即生效。
    custom = settings.skills_dir / "my-skill" / "SKILL.md"
    custom.parent.mkdir(parents=True, exist_ok=True)
    custom.write_text("---\nname: 我的技能\ndescription: 自定义\n---\n\n步骤正文", encoding="utf-8")
    listed_again = client.get("/api/agent/prompt-skills").json()
    mine = next(skill for skill in listed_again if skill["id"] == "my-skill")
    assert mine["source"] == "user" and mine["name"] == "我的技能"

    # 路径穿越拒绝。
    assert client.get("/api/agent/prompt-skills/..%2F..%2Fetc").status_code == 404

    index = prompt_skills.skills_index_for_prompt()
    assert "transcript-rough-cut" in index and "my-skill" in index
