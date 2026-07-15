from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
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
) -> TurnResult:
    if adapter == "claude":
        return _run_claude(prompt, system_prompt, api_base, token, adapter_session_id)
    if adapter == "opencode":
        return _run_opencode(prompt, system_prompt, api_base, token, adapter_session_id)
    raise AdapterError(f"Unknown agent adapter: {adapter}")


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


def _run_claude(
    prompt: str, system_prompt: str, api_base: str, token: str, adapter_session_id: str | None
) -> TurnResult:
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as handle:
        json.dump(mibu_mcp_config(api_base, token), handle)
        config_path = handle.name
    try:
        command = build_claude_command(prompt, system_prompt, config_path, adapter_session_id)
        process = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=TURN_TIMEOUT_SECONDS,
            env={**os.environ},
        )
        if process.returncode != 0:
            raise AdapterError(_tail(process.stderr) or f"agent exited with code {process.returncode}")
        try:
            payload = json.loads(process.stdout)
        except json.JSONDecodeError as exc:
            raise AdapterError(f"Unparseable agent output: {_tail(process.stdout)}") from exc
        if payload.get("is_error"):
            raise AdapterError(_tail(str(payload.get("result", "agent error"))))
        return TurnResult(text=str(payload.get("result", "")).strip(), adapter_session_id=payload.get("session_id"))
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
