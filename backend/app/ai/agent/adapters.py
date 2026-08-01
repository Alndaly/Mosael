from __future__ import annotations

import json
import threading
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

"""
Agent CLI adapters: Open Studio hosts a specialized external coding-agent (pi — the
instead of a homegrown loop. The agent gets
Open Studio's MCP server (with a session token) as its tool surface; mutations still
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
    adapter_state: object | None = None  # pi: 序列化的消息数组,用于下一轮多轮记忆
    usage: dict | None = None
    #: 本轮结束时的上下文水位 {tokens, window}。窗口按**当前模型**给 —— 换模型上限就变,
    #: 用一个全局常量会在小窗口模型上把界面显示成"还早得很"。
    context: dict | None = None
    #: 本轮开始前发生的压缩;没发生为 None。必须一路带到前端 —— 压缩静默进行的话,
    #: 用户不会知道早期消息已经不在上下文里了。
    compaction: dict | None = None

def run_turn(
    adapter: str,
    *,
    session_key: str = "",
    prompt: str,
    system_prompt: str,
    api_base: str,
    token: str,
    on_delta: "Callable[[str], None] | None" = None,
    provider: dict | None = None,
    model: str | None = None,
    workspace_id: str = "",
    adapter_state: object | None = None,
    force_compact: bool = False,
    on_tool: "Callable[[dict], None] | None" = None,
) -> TurnResult:
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
            force_compact=force_compact,
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


def _proxy_env(base: dict[str, str]) -> dict[str, str]:
    """给 sidecar 的环境补上代理设置。自开一个会话:调用方持有的那个 db 可能正处在
    一次回合的事务里,而这里只是读一行配置,不该被卷进去。"""
    from app.core.db import SessionLocal
    from app.domain.network import subprocess_env

    with SessionLocal() as db:
        return subprocess_env(db, base)


def pi_sidecar_command() -> tuple[str, str]:
    """跑 sidecar 用的 (node, 脚本路径)。登录流程也起同一个 sidecar,所以这里是公开的。"""
    node = os.environ.get("OPEN_STUDIO_AGENT_BIN_NODE") or shutil.which("node") or "node"
    repo_root = Path(__file__).resolve().parents[4]
    sidecar = os.environ.get("OPEN_STUDIO_PI_SIDECAR") or str(repo_root / "agent-sidecar" / "dist" / "sidecar.cjs")
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
    force_compact: bool = False,
) -> TurnResult:
    """Spawn the pi sidecar (Node, embeds pi-agent-core) for one turn and stream
    its JSONL events. The sidecar's tools call back into Open Studio's REST with the
    service token; mutations still flow through confirmation cards. adapter_state
    carries pi's serialized messages for multi-turn memory (round-tripped)."""
    if not provider or not model:
        raise AdapterError("未配置可用的 AI 供应商;请在设置里添加并启用一个供应商。")
    node, sidecar = pi_sidecar_command()
    if not Path(sidecar).exists():
        raise AdapterError(f"pi sidecar 未构建:{sidecar}(在 agent-sidecar 目录执行 pnpm build)")

    frame = {
        "type": "run_turn",
        "turnId": "turn",
        "prompt": prompt,
        "systemPrompt": system_prompt,
        "workspaceId": workspace_id,
        # 确认卡据此归属到本次会话,只在它自己那次对话里内联出现(见 mcp_server._SESSION_ID)。
        "sessionId": session_id,
        "apiBase": api_base,
        "token": token,
        "provider": {
            "baseUrl": provider.get("base_url", ""),
            "apiKey": provider.get("api_key", ""),
            "vendor": provider.get("vendor", ""),
            # 供应商目录给了才带上;没有就不传,由 sidecar 用保守回退而不是硬编一个大数。
            "contextWindow": provider.get("context_window"),
            "maxOutputTokens": provider.get("max_output_tokens"),
            # 按模型的手动覆盖。都对应 pi 里真实生效的开关(thinking 格式、图片输入、
            # reasoning_effort、developer 角色),没填就不传,由 sidecar 保持保守默认。
            "reasoning": provider.get("reasoning"),
            "vision": provider.get("vision"),
            "reasoningEffort": provider.get("reasoning_effort"),
            "developerRole": provider.get("developer_role"),
            # 订阅计划(OAuth):pi 内置 Provider 的 id + 当前凭据。刷新后由 sidecar 写回后端。
            "piProvider": provider.get("pi_provider", ""),
            "credential": provider.get("credential"),
            "profileId": provider.get("profile_id", ""),
        },
        "model": model,
        "sessionState": adapter_state,
        # 界面上的「立即压缩」:跳过水位判断,本轮开始前先整理一次上下文。
        "forceCompact": force_compact,
    }
    # 打包版把 Electron 二进制当 node 用(OPEN_STUDIO_AGENT_BIN_NODE),需 ELECTRON_RUN_AS_NODE=1;
    # 真 node(dev)会忽略该变量,所以仅在显式指定 node 时加,最稳妥。
    env = {**os.environ}
    if os.environ.get("OPEN_STUDIO_AGENT_BIN_NODE"):
        env["ELECTRON_RUN_AS_NODE"] = "1"
    # 出站代理:Node 默认不认这几个变量,sidecar 自己会装 EnvHttpProxyAgent 来读(见 proxy.ts)。
    env = _proxy_env(env)
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
    result_context: dict | None = None
    result_compaction: dict | None = None
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
            context = event.get("context")
            result_context = context if isinstance(context, dict) else None
            compaction = event.get("compaction")
            result_compaction = compaction if isinstance(compaction, dict) else None
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
        return TurnResult(text=result_text, adapter_state=result_state, usage=result_usage, context=result_context, compaction=result_compaction)
    if not result_text.strip() and not saw_tool:
        # A turn that finished with neither text nor tool calls means the model call itself failed
        # (unreachable base_url, wrong model name, bad key) and pi swallowed it. Never let that
        # surface as an empty chat bubble — the user has to be told why nothing came back.
        raise AdapterError(stderr_tail or f"模型没有返回任何内容。{_PROVIDER_HINT}")
    return TurnResult(
        text=result_text.strip(),
        adapter_state=result_state,
        usage=result_usage,
        context=result_context,
        compaction=result_compaction,
    )
def _tail(text: str, limit: int = 500) -> str:
    return text.strip()[-limit:]


@dataclass
class CompactionResult:
    """一次手动压缩的结果。`compaction` 为 None 表示没有可压缩的内容(对话还太短)。"""

    adapter_state: object | None
    context: dict | None
    compaction: dict | None


def compact_session(
    *,
    api_base: str,
    token: str,
    provider: dict | None,
    model: str | None,
    adapter_state: object | None,
) -> CompactionResult:
    """只压缩不对话 —— 界面上的「立即压缩」。

    单独走一次 sidecar 而不是"下一轮顺带压":用户点的是"现在把上下文整理掉",要求他先
    再问一句话才生效,和这个动作的语义对不上。摘要仍然会花一次模型调用,所以它是手动的。
    """
    if not provider or not model:
        raise AdapterError("未配置可用的 AI 供应商;请在设置里添加并启用一个供应商。")
    node, sidecar = pi_sidecar_command()
    if not Path(sidecar).exists():
        raise AdapterError(f"pi sidecar 未构建:{sidecar}(在 agent-sidecar 目录执行 pnpm build)")
    frame = {
        "type": "compact",
        "turnId": "compact",
        "systemPrompt": "",
        "apiBase": api_base,
        "token": token,
        "provider": {
            "baseUrl": provider.get("base_url", ""),
            "apiKey": provider.get("api_key", ""),
            "vendor": provider.get("vendor", ""),
            "contextWindow": provider.get("context_window"),
            "maxOutputTokens": provider.get("max_output_tokens"),
            "piProvider": provider.get("pi_provider", ""),
            "credential": provider.get("credential"),
            "profileId": provider.get("profile_id", ""),
        },
        "model": model,
        "sessionState": adapter_state,
    }
    env = {**os.environ}
    if os.environ.get("OPEN_STUDIO_AGENT_BIN_NODE"):
        env["ELECTRON_RUN_AS_NODE"] = "1"
    env = _proxy_env(env)
    process = subprocess.Popen(
        [node, sidecar], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps(frame) + "\n")
    process.stdin.flush()
    process.stdin.close()
    # 摘要要真的调一次模型,给和一轮对话同量级的时限。
    child = ChildProcess(process, TURN_TIMEOUT_SECONDS)
    for line in child.lines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "compacted":
            child.finish()
            return CompactionResult(
                adapter_state=event.get("sessionState"),
                context=event.get("context") if isinstance(event.get("context"), dict) else None,
                compaction=event.get("compaction") if isinstance(event.get("compaction"), dict) else None,
            )
        if event.get("type") == "error":
            child.finish()
            raise AdapterError(_tail(str(event.get("message", "压缩失败"))))
    raise AdapterError(_tail(child.finish()) or "压缩没有返回结果")


def refresh_oauth_credential(*, api_base: str, token: str, pi_provider: str, profile_id: str, credential: dict | None) -> bool:
    """刷新一次订阅计划的 OAuth 凭据。返回 False 表示这个档案根本没登录过。

    **刷新协议不在这边**:各家的 refresh flow 在 pi 的 Provider 定义里,这里只是让 sidecar
    调一次 `models.getAuth` —— 它返回前会刷新并把新凭据经租约写回后端。自己在 Python 里
    实现刷新等于把六家协议再抄一遍,而当初把订阅制交给 pi 就是为了不抄。
    """
    node, sidecar = pi_sidecar_command()
    if not Path(sidecar).exists():
        raise AdapterError(f"pi sidecar 未构建:{sidecar}(在 agent-sidecar 目录执行 pnpm build)")
    frame = {
        "type": "refresh_credential",
        "turnId": "refresh",
        "piProvider": pi_provider,
        "profileId": profile_id,
        "credential": credential,
        "apiBase": api_base,
        "token": token,
    }
    env = {**os.environ}
    if os.environ.get("OPEN_STUDIO_AGENT_BIN_NODE"):
        env["ELECTRON_RUN_AS_NODE"] = "1"
    env = _proxy_env(env)
    process = subprocess.Popen(
        [node, sidecar], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
    )
    assert process.stdin is not None and process.stdout is not None
    process.stdin.write(json.dumps(frame) + "\n")
    process.stdin.flush()
    process.stdin.close()
    # 刷新是一次 token 交换,不该等到对话那种时限。
    child = ChildProcess(process, 60)
    for line in child.lines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "credential_refreshed":
            child.finish()
            return bool(event.get("refreshed"))
        if event.get("type") == "error":
            child.finish()
            raise AdapterError(_tail(str(event.get("message", "刷新凭据失败"))))
    raise AdapterError(_tail(child.finish()) or "刷新凭据没有返回结果")
