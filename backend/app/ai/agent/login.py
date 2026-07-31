"""订阅计划的登录会话(设备码 / 浏览器授权)。

登录和跑一轮对话是两件事,所以不共用那条通道:授权由**用户在界面上**完成,可能几十秒到几分钟,
中途还要往返提问-作答。塞进一轮对话里既没有 UI 可展示,也会把那一轮长时间卡死。

这里管的是「一次登录」的生命周期:起一个 sidecar 进程跑 pi 的授权流程,把它吐出来的事件
(授权链接、设备码、进度、提问)收进内存里的会话状态,前端轮询取用、作答回灌。凭据不经过这里
—— sidecar 直接经 CredentialStore 写回后端,和刷新走同一条路径(见 agent_credentials 路由)。

**授权流程本身一个字都不在这边**:各家的设备码 / PKCE / 粘贴授权码全在 pi 的 Provider 定义里。
新增一家订阅供应商只需要在 VENDOR_PRESETS 里加一条。
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field

from app.ai.agent.adapters import pi_sidecar_command

logger = logging.getLogger(__name__)

#: 授权流程的上限。设备码通常 10 分钟过期;超时就当用户放弃了,别把进程永远挂着。
LOGIN_TIMEOUT_SECONDS = 15 * 60
#: 完成后保留状态多久,给前端最后一次轮询取结果的机会。
RETAIN_SECONDS = 120


@dataclass
class LoginSession:
    login_id: str
    profile_id: str
    status: str = "running"  # running | done | error | cancelled
    #: pi 的 AuthEvent 原样堆叠(授权链接、设备码、进度)。前端按序展示。
    events: list[dict] = field(default_factory=list)
    #: 当前待用户作答的提问;没有则 None。
    prompt: dict | None = None
    error: str = ""
    #: 登录成功后该账号实际可用的模型目录。
    models: list[dict] = field(default_factory=list)
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    process: subprocess.Popen | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


_sessions: dict[str, LoginSession] = {}
_sessions_lock = threading.Lock()


class LoginError(RuntimeError):
    pass


def _prune() -> None:
    now = time.monotonic()
    with _sessions_lock:
        for key, session in list(_sessions.items()):
            if session.finished_at is not None and now - session.finished_at > RETAIN_SECONDS:
                _sessions.pop(key, None)


def get_session(login_id: str) -> LoginSession | None:
    _prune()
    with _sessions_lock:
        return _sessions.get(login_id)


def session_for_profile(profile_id: str) -> LoginSession | None:
    """该档案上进行中的登录 —— 前端刷新页面后要能接回去。"""
    _prune()
    with _sessions_lock:
        for session in _sessions.values():
            if session.profile_id == profile_id and session.status == "running":
                return session
    return None


def _finish(session: LoginSession, status: str, error: str = "") -> None:
    with session.lock:
        if session.status != "running":
            return
        session.status = status
        session.error = error
        session.prompt = None
        session.finished_at = time.monotonic()


def _reader(session: LoginSession) -> None:
    """读 sidecar 的事件流,更新会话状态。进程退出即结束。"""
    process = session.process
    assert process is not None and process.stdout is not None
    try:
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("login sidecar non-JSON line: %s", line[:200])
                continue
            kind = event.get("type")
            with session.lock:
                if kind == "auth_event":
                    session.events.append(event.get("event") or {})
                elif kind == "auth_prompt":
                    session.prompt = {
                        "prompt_id": event.get("promptId", ""),
                        "prompt_type": event.get("promptType", "text"),
                        "message": event.get("message", ""),
                        "placeholder": event.get("placeholder") or "",
                        "options": event.get("options") or [],
                    }
                elif kind == "auth_done":
                    session.models = list(event.get("models") or [])
            if kind == "auth_done":
                _finish(session, "done")
                break
            if kind == "error":
                _finish(session, "error", str(event.get("message", ""))[:500])
                break
    except Exception as exc:  # noqa: BLE001 - 读取失败只是这次登录失败
        logger.warning("login reader failed: %s", exc)
        _finish(session, "error", str(exc)[:500])
    finally:
        # 进程还活着就意味着流程没走完(例如 sidecar 卡在等待作答),收掉它。
        _terminate(session)
        _finish(session, "error", session.error or "登录进程意外结束")


def _watchdog(session: LoginSession) -> None:
    deadline = session.started_at + LOGIN_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        with session.lock:
            if session.status != "running":
                return
        time.sleep(1.0)
    _terminate(session)
    _finish(session, "error", "授权超时,请重新发起登录")


def _terminate(session: LoginSession) -> None:
    process = session.process
    if process is None or process.poll() is not None:
        return
    try:
        process.terminate()
    except Exception:  # noqa: BLE001
        pass


def _send(session: LoginSession, frame: dict) -> bool:
    process = session.process
    if process is None or process.stdin is None or process.poll() is not None:
        return False
    try:
        process.stdin.write(json.dumps(frame) + "\n")
        process.stdin.flush()
        return True
    except Exception:  # noqa: BLE001 - 进程已经没了
        return False


def start_login(
    *,
    login_id: str,
    profile_id: str,
    pi_provider: str,
    api_base: str,
    token: str,
    credential: dict | None,
) -> LoginSession:
    """起一次登录。同一档案已有进行中的登录时直接复用,避免两份设备码把用户绕晕。"""
    existing = session_for_profile(profile_id)
    if existing is not None:
        return existing

    node, sidecar = pi_sidecar_command()
    if not os.path.exists(sidecar):
        raise LoginError(f"pi sidecar 未构建:{sidecar}(在 agent-sidecar 目录执行 pnpm build)")

    env = {**os.environ}
    if os.environ.get("OPEN_STUDIO_AGENT_BIN_NODE"):
        env["ELECTRON_RUN_AS_NODE"] = "1"
    process = subprocess.Popen(
        [node, sidecar],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        env=env,
    )
    session = LoginSession(login_id=login_id, profile_id=profile_id, process=process)
    with _sessions_lock:
        _sessions[login_id] = session

    if not _send(
        session,
        {
            "type": "auth_login",
            "loginId": login_id,
            "piProvider": pi_provider,
            "profileId": profile_id,
            "apiBase": api_base,
            "token": token,
            "credential": credential,
        },
    ):
        _finish(session, "error", "登录进程启动失败")
        raise LoginError("登录进程启动失败")

    threading.Thread(target=_reader, args=(session,), daemon=True).start()
    threading.Thread(target=_watchdog, args=(session,), daemon=True).start()
    return session


def answer(login_id: str, prompt_id: str, value: str) -> bool:
    session = get_session(login_id)
    if session is None or session.status != "running":
        return False
    with session.lock:
        current = session.prompt
        if current is None or current.get("prompt_id") != prompt_id:
            return False
        session.prompt = None
    return _send(session, {"type": "auth_answer", "promptId": prompt_id, "answer": value})


def cancel(login_id: str) -> bool:
    session = get_session(login_id)
    if session is None:
        return False
    _send(session, {"type": "auth_cancel", "loginId": login_id})
    _terminate(session)
    _finish(session, "cancelled")
    return True
