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
Agent CLI adapters: Mibu hosts a specialized external coding-agent (pi — the
`claude` adapter is an alternative) instead of a homegrown loop. The agent gets
Mibu's MCP server (with a session token) as its tool surface; mutations still
flow through the confirmation cards.
"""

TURN_TIMEOUT_SECONDS = 600


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class TurnResult:
    text: str
    adapter_session_id: str | None = None
    adapter_state: object | None = None  # pi: 序列化的消息数组,用于下一轮多轮记忆


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
    adapter_state: object | None = None,
    on_tool: "Callable[[dict], None] | None" = None,
) -> TurnResult:
    if adapter == "claude":
        return _run_claude_streaming(prompt, system_prompt, api_base, token, adapter_session_id, on_delta)
    if adapter == "pi":
        return _run_pi(
            prompt, system_prompt, api_base, token, workspace_id, provider, model, adapter_state, on_delta, on_tool
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
    adapter_state: object | None,
    on_delta: Callable[[str], None] | None,
    on_tool: Callable[[dict], None] | None = None,
) -> TurnResult:
    """Spawn the pi sidecar (Node, embeds pi-agent-core) for one turn and stream
    its JSONL events. The sidecar's tools call back into Mibu's REST with the
    service token; mutations still flow through confirmation cards. adapter_state
    carries pi's serialized messages for multi-turn memory (round-tripped)."""
    if not provider or not model:
        raise AdapterError("未配置可用的 AI 供应商;请在设置里添加并启用一个供应商。")
    node, sidecar = _pi_sidecar_command()
    if not Path(sidecar).exists():
        raise AdapterError(f"pi sidecar 未构建:{sidecar}(在 agent-sidecar 目录执行 pnpm build)")

    frame = {
        "type": "run_turn",
        "turnId": "turn",
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
        "sessionState": adapter_state,
    }
    # 打包版把 Electron 二进制当 node 用(MIBU_AGENT_BIN_NODE),需 ELECTRON_RUN_AS_NODE=1;
    # 真 node(dev)会忽略该变量,所以仅在显式指定 node 时加,最稳妥。
    env = {**os.environ}
    if os.environ.get("MIBU_AGENT_BIN_NODE"):
        env["ELECTRON_RUN_AS_NODE"] = "1"
    process = subprocess.Popen(
        [node, sidecar], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps(frame) + "\n")
    process.stdin.flush()
    process.stdin.close()

    result_text: str | None = None
    result_state: object | None = None
    saw_tool = False
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
        elif kind in ("tool_start", "tool_end"):
            saw_tool = True
            if on_tool is not None:
                on_tool(event)
        elif kind == "turn_done":
            result_text = str(event.get("text", ""))
            result_state = event.get("sessionState")
        elif kind == "error":
            raise AdapterError(_tail(str(event.get("message", "pi sidecar error"))))
    process.wait(timeout=TURN_TIMEOUT_SECONDS)
    stderr_tail = _tail(process.stderr.read() if process.stderr else "")
    if result_text is None:
        raise AdapterError(stderr_tail or f"pi sidecar exited with code {process.returncode}")
    if not result_text.strip() and not saw_tool:
        # A turn that finished with neither text nor tool calls means the model call itself failed
        # (unreachable base_url, wrong model name, bad key) and pi swallowed it. Never let that
        # surface as an empty chat bubble — the user has to be told why nothing came back.
        raise AdapterError(
            stderr_tail
            or "模型没有返回任何内容。请检查 AI 供应商配置:base_url 是否完整"
            "(含端口与 /v1,如 http://localhost:11434/v1)、模型名是否存在、服务是否可达。"
        )
    return TurnResult(text=result_text.strip(), adapter_state=result_state)


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




def _tail(text: str, limit: int = 500) -> str:
    return text.strip()[-limit:]
