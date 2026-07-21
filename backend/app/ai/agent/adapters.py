from __future__ import annotations

import json
import threading
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

from app.core.child_process import ChildProcess

TURN_TIMEOUT_SECONDS = 600



_PROVIDER_HINT = (
    "请检查 AI 供应商配置:base_url 是否为完整的 OpenAI 兼容端点"
    "(含端口与 /v1,如 http://localhost:11434/v1)、模型名是否存在、服务是否可达。"
)


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class TurnResult:
    text: str
    adapter_session_id: str | None = None
    adapter_state: object | None = None  # pi: 序列化的消息数组,用于下一轮多轮记忆
    usage: dict | None = None


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
    session_key: str = "",
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
            prompt,
            system_prompt,
            api_base,
            token,
            workspace_id,
            provider,
            model,
            adapter_state,
            on_delta,
            on_tool,
            session_id=session_key,
        )
    raise AdapterError(f"Unknown agent adapter: {adapter}")


class _LiveTurn:
    """The stdin of a sidecar whose turn is still running.

    Steering only exists if a running turn can still be written to. The sidecar used to have
    its stdin closed the moment the request was sent, which made the channel one-way for the
    entire turn — the only window in which a correction is worth anything.
    """

    def __init__(self, stdin, turn_id: str) -> None:
        self._stdin = stdin
        self._lock = threading.Lock()
        self.turn_id = turn_id
        self.closed = False

    def send(self, frame: dict) -> bool:
        """Write one frame. False when the turn already ended, so callers can fall back."""
        with self._lock:
            if self.closed:
                return False
            try:
                self._stdin.write(json.dumps(frame) + "\n")
                self._stdin.flush()
                return True
            except (BrokenPipeError, ValueError):
                # The turn finished between the lookup and this write. Not an error: the
                # caller sends the message as an ordinary next turn instead.
                self.closed = True
                return False

    def close(self) -> None:
        with self._lock:
            self.closed = True
            try:
                self._stdin.close()
            except Exception:  # noqa: BLE001 — the process may already be gone
                pass


#: Running turns by session id. An API request arrives on a different thread from the one
#: awaiting the turn, so this is how the two meet.
_LIVE: dict[str, _LiveTurn] = {}
_LIVE_LOCK = threading.Lock()


def steer_turn(session_id: str, prompt: str, mode: str = "steer") -> bool:
    """Inject a message into the running turn. False when there is no turn to inject into."""
    with _LIVE_LOCK:
        live = _LIVE.get(session_id)
    if live is None:
        return False
    return live.send({"type": "steer", "turnId": live.turn_id, "prompt": prompt, "mode": mode})


def set_turn_queue(session_id: str, prompts: list[str]) -> bool:
    """Replace the running turn's steering queue. False when there is no turn to talk to.

    Declaring the whole queue rather than deleting one entry is what makes per-message cancel
    possible at all: pi can clear its queue but cannot remove a single item from it.
    """
    with _LIVE_LOCK:
        live = _LIVE.get(session_id)
    if live is None:
        return False
    return live.send({"type": "queue", "turnId": live.turn_id, "prompts": prompts})


def abort_turn(session_id: str) -> bool:
    """Stop the running turn, keeping whatever it produced. False when nothing is running."""
    with _LIVE_LOCK:
        live = _LIVE.get(session_id)
    if live is None:
        return False
    return live.send({"type": "abort", "turnId": live.turn_id})


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
    session_id: str = "",
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
    # stdin deliberately stays open for the life of the turn — see _LiveTurn. Closing it here
    # is what made steering impossible before.
    live = _LiveTurn(process.stdin, frame["turnId"])
    if session_id:
        with _LIVE_LOCK:
            _LIVE[session_id] = live

    child = ChildProcess(process, TURN_TIMEOUT_SECONDS)
    result_text: str | None = None
    result_state: object | None = None
    result_usage: dict | None = None
    saw_tool = False
    aborted = False
    for line in child.lines():
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
            usage = event.get("usage")
            result_usage = usage if isinstance(usage, dict) else None
            # Stop reading here rather than waiting for the process to exit. stdin now stays
            # open for the whole turn so steering has somewhere to go, which means the sidecar's
            # readline loop no longer ends on its own — waiting for EOF left every turn
            # "running" until the timeout, long after the answer had finished streaming.
            break
        elif kind == "error":
            detail = _tail(str(event.get("message", "pi sidecar error")))
            # 还没产出任何文本/工具调用就失败,基本都是供应商配置问题(端点不对、模型不存在、
            # 鉴权失败),给一句可操作的提示;已经跑起来后的失败就只报原始错误。
            if not saw_tool:
                raise AdapterError(f"{detail}\n{_PROVIDER_HINT}")
            raise AdapterError(detail)
        elif kind == "aborted":
            aborted = True
    live.close()
    if session_id:
        with _LIVE_LOCK:
            if _LIVE.get(session_id) is live:
                del _LIVE[session_id]
    stderr_tail = _tail(child.finish())
    if child.timed_out:
        raise AdapterError(
            f"智能体运行超过 {TURN_TIMEOUT_SECONDS} 秒未返回,已终止。" + (f"\n{stderr_tail}" if stderr_tail else "")
        )
    if result_text is None:
        raise AdapterError(stderr_tail or f"pi sidecar exited with code {process.returncode}")
    if aborted:
        # A stopped turn is a normal outcome, not a failure: the user asked for it, and the
        # partial text is real output they watched arrive.
        return TurnResult(text=result_text, adapter_session_id=None, adapter_state=result_state, usage=result_usage)
    if not result_text.strip() and not saw_tool:
        # A turn that finished with neither text nor tool calls means the model call itself failed
        # (unreachable base_url, wrong model name, bad key) and pi swallowed it. Never let that
        # surface as an empty chat bubble — the user has to be told why nothing came back.
        raise AdapterError(stderr_tail or f"模型没有返回任何内容。{_PROVIDER_HINT}")
    return TurnResult(text=result_text.strip(), adapter_state=result_state, usage=result_usage)


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
        child = ChildProcess(process, TURN_TIMEOUT_SECONDS)
        for line in child.lines():
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
        stderr_tail = _tail(child.finish())
        if child.timed_out:
            raise AdapterError(
                f"智能体运行超过 {TURN_TIMEOUT_SECONDS} 秒未返回,已终止。"
                + (f"\n{stderr_tail}" if stderr_tail else "")
            )
        # 优先透传 CLI 自己给出的结果错误(如 "Not logged in · Please run /login"),
        # 否则非零退出只会显示无意义的 "exited with code 1"。
        if is_error and result_text:
            raise AdapterError(_tail(result_text))
        if process.returncode != 0:
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
