from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

"""
Agent CLI adapters: Mibu hosts a specialized external coding-agent
(opencode-style) instead of a homegrown loop. The agent gets Mibu's MCP
server (with a session token) as its tool surface; mutations still flow
through the confirmation cards.
"""

TURN_TIMEOUT_SECONDS = 600


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class TurnResult:
    text: str
    adapter_session_id: str | None = None


def mibu_mcp_config(api_base: str, token: str) -> dict:
    backend_dir = Path(__file__).resolve().parents[3]
    python = backend_dir / ".venv" / "bin" / "python"
    return {
        "mcpServers": {
            "mibu": {
                "command": str(python if python.exists() else "python3"),
                "args": [str(backend_dir / "mcp_server.py")],
                "env": {"MIBU_API": api_base, "MIBU_TOKEN": token},
            }
        }
    }


def run_turn(
    adapter: str,
    *,
    prompt: str,
    system_prompt: str,
    api_base: str,
    token: str,
    adapter_session_id: str | None,
    on_delta: "Callable[[str], None] | None" = None,
    provider: dict | None = None,
    model: str | None = None,
    workspace_id: str = "",
) -> TurnResult:
    if adapter == "claude":
        return _run_claude_streaming(prompt, system_prompt, api_base, token, adapter_session_id, on_delta)
    if adapter == "opencode":
        return _run_opencode(prompt, system_prompt, api_base, token, adapter_session_id)
    if adapter == "pi":
        return _run_pi(
            prompt, system_prompt, api_base, token, workspace_id, provider, model, adapter_session_id, on_delta
        )
    raise AdapterError(f"Unknown agent adapter: {adapter}")


def _pi_sidecar_command() -> tuple[str, str]:
    node = os.environ.get("MIBU_AGENT_BIN_NODE") or shutil.which("node") or "node"
    repo_root = Path(__file__).resolve().parents[4]
    sidecar = os.environ.get("MIBU_PI_SIDECAR") or str(repo_root / "agent-sidecar" / "dist" / "sidecar.cjs")
    return node, sidecar


def _run_pi(
    prompt: str,
    system_prompt: str,
    api_base: str,
    token: str,
    workspace_id: str,
    provider: dict | None,
    model: str | None,
    adapter_session_id: str | None,
    on_delta: Callable[[str], None] | None,
) -> TurnResult:
    """Spawn the pi sidecar (Node, embeds pi-agent-core) for one turn and stream
    its JSONL events. The sidecar's tools call back into Mibu's REST with the
    service token; mutations still flow through confirmation cards."""
    if not provider or not model:
        raise AdapterError("未配置可用的 AI 供应商;请在设置里添加并启用一个供应商。")
    node, sidecar = _pi_sidecar_command()
    if not Path(sidecar).exists():
        raise AdapterError(f"pi sidecar 未构建:{sidecar}(在 agent-sidecar 目录执行 pnpm build)")

    frame = {
        "type": "run_turn",
        "turnId": adapter_session_id or "turn",
        "prompt": prompt,
        "systemPrompt": system_prompt,
        "workspaceId": workspace_id,
        "apiBase": api_base,
        "token": token,
        "provider": {
            "baseUrl": provider.get("base_url", ""),
            "apiKey": provider.get("api_key", ""),
            "vendor": provider.get("vendor", ""),
        },
        "model": model,
    }
    process = subprocess.Popen(
        [node, sidecar], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env={**os.environ}
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps(frame) + "\n")
    process.stdin.flush()
    process.stdin.close()

    result_text: str | None = None
    for line in process.stdout:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "text_delta" and on_delta is not None:
            on_delta(str(event.get("delta", "")))
        elif kind == "turn_done":
            result_text = str(event.get("text", ""))
        elif kind == "error":
            raise AdapterError(_tail(str(event.get("message", "pi sidecar error"))))
    process.wait(timeout=TURN_TIMEOUT_SECONDS)
    if result_text is None:
        stderr_tail = _tail(process.stderr.read() if process.stderr else "")
        raise AdapterError(stderr_tail or f"pi sidecar exited with code {process.returncode}")
    return TurnResult(text=result_text.strip(), adapter_session_id=adapter_session_id)


def build_claude_command(
    prompt: str, system_prompt: str, mcp_config_path: str, adapter_session_id: str | None
) -> list[str]:
    binary = os.environ.get("MIBU_AGENT_BIN_CLAUDE") or shutil.which("claude") or "claude"
    command = [
        binary,
        "-p", prompt,
        "--output-format", "json",
        "--append-system-prompt", system_prompt,
        "--mcp-config", mcp_config_path,
        "--strict-mcp-config",
        "--allowedTools", "mcp__mibu",
    ]
    if adapter_session_id:
        command += ["--resume", adapter_session_id]
    return command


def _run_claude_streaming(
    prompt: str,
    system_prompt: str,
    api_base: str,
    token: str,
    adapter_session_id: str | None,
    on_delta: Callable[[str], None] | None = None,
) -> TurnResult:
    """stream-json mode: emits token-level text deltas via on_delta while running."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(mibu_mcp_config(api_base, token), handle)
        config_path = handle.name
    try:
        command = build_claude_command(prompt, system_prompt, config_path, adapter_session_id)
        stream_index = command.index("json")
        command[stream_index] = "stream-json"
        command += ["--include-partial-messages", "--verbose"]

        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**os.environ},
        )
        result_text: str | None = None
        session_id: str | None = None
        is_error = False
        assert process.stdout is not None
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = event.get("type")
            if kind == "stream_event" and on_delta is not None:
                inner = event.get("event") or {}
                if inner.get("type") == "content_block_delta":
                    delta = inner.get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        on_delta(str(delta["text"]))
            elif kind == "result":
                result_text = str(event.get("result", ""))
                session_id = event.get("session_id")
                is_error = bool(event.get("is_error"))
        process.wait(timeout=TURN_TIMEOUT_SECONDS)
        # 优先透传 CLI 自己给出的结果错误(如 "Not logged in · Please run /login"),
        # 否则非零退出只会显示无意义的 "exited with code 1"。
        if is_error and result_text:
            raise AdapterError(_tail(result_text))
        if process.returncode != 0:
            stderr_tail = _tail(process.stderr.read() if process.stderr else "")
            raise AdapterError(stderr_tail or f"agent exited with code {process.returncode}")
        if result_text is None:
            raise AdapterError("Agent produced no result event")
        if is_error:
            raise AdapterError(_tail(result_text or "agent error"))
        return TurnResult(text=result_text.strip(), adapter_session_id=session_id)
    finally:
        Path(config_path).unlink(missing_ok=True)


def _run_opencode(
    prompt: str, system_prompt: str, api_base: str, token: str, adapter_session_id: str | None
) -> TurnResult:
    """Best-effort opencode support: per-session home dir carries opencode.json MCP config."""
    binary = os.environ.get("MIBU_AGENT_BIN_OPENCODE") or shutil.which("opencode") or "opencode"
    home = Path(tempfile.gettempdir()) / "mibu-opencode" / (adapter_session_id or "default")
    home.mkdir(parents=True, exist_ok=True)
    backend_dir = Path(__file__).resolve().parents[3]
    python = backend_dir / ".venv" / "bin" / "python"
    (home / "opencode.json").write_text(
        json.dumps(
            {
                "$schema": "https://opencode.ai/config.json",
                "instructions": ["mibu-agent.md"],
                "mcp": {
                    "mibu": {
                        "type": "local",
                        "command": [str(python), str(backend_dir / "mcp_server.py")],
                        "environment": {"MIBU_API": api_base, "MIBU_TOKEN": token},
                    }
                },
            }
        )
    )
    (home / "mibu-agent.md").write_text(system_prompt)
    process = subprocess.run(
        [binary, "run", prompt],
        capture_output=True,
        text=True,
        timeout=TURN_TIMEOUT_SECONDS,
        cwd=home,
        env={**os.environ},
    )
    if process.returncode != 0:
        raise AdapterError(_tail(process.stderr) or f"agent exited with code {process.returncode}")
    return TurnResult(text=process.stdout.strip(), adapter_session_id=adapter_session_id)


def _tail(text: str, limit: int = 500) -> str:
    return text.strip()[-limit:]
