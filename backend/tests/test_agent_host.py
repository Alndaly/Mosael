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

    def fake_run_turn(adapter, *, prompt, system_prompt, api_base, token, adapter_session_id):
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


def test_second_message_while_running_rejected(monkeypatch) -> None:
    def slow_run_turn(*args, **kwargs):
        time.sleep(1.5)
        return TurnResult(text="ok")

    monkeypatch.setattr(host, "run_turn", slow_run_turn)

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    session = client.post("/api/agent/sessions", json={"workspace_id": ws["id"]}).json()
    first = client.post(f"/api/agent/sessions/{session['id']}/messages", json={"content": "one"})
    assert first.status_code == 200
    second = client.post(f"/api/agent/sessions/{session['id']}/messages", json={"content": "two"})
    assert second.status_code == 409
