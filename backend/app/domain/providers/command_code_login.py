"""Command Code 的浏览器登录:在 Studio 里点一下,把 API Key 交回本机。

**它为什么不是 pi 那一套。** 别的订阅计划(Claude Pro/Max、Codex、Copilot)由 pi 的 Provider 定义
驱动授权流程,后端只转发事件;Command Code 没有 pi Provider,它自己的 CLI 是这么做的:

    起一个**只监听回环**的一次性 HTTP 服务 → 打开
    `https://commandcode.ai/studio/auth/cli?callback=http://localhost:PORT/callback&state=…`
    → Studio 在用户登录后把 `{apiKey, state, userId, userName, keyName}` **POST 回本机**
    → CLI 校验 `GET {api}/alpha/whoami` 之后把它存成凭据(Key 不过期)。

这里照做,只是把「存」接到 Mosael 的连接上:同一个 Key 认证它的 CLI 和 Provider API,所以拿到之后
按 **api_key** 存进这条连接 —— 聊天照旧走 OpenAI 兼容通道(见 presets 的 `command-code`)。

安全上的三条:
  · 只绑 127.0.0.1,端口在 5959 起的十来个里挑一个(和它的 CLI 一致);
  · `state` 必须对上:先发起、后回调,别让一个半路来的 POST 把别人的 Key 塞进来;
  · 超时就作废(默认 180 秒),服务在拿到第一条合法回调后立刻关掉。
"""

from __future__ import annotations

import json
import secrets
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

STUDIO_AUTH_URL = "https://commandcode.ai/studio/auth/cli"
#: 它的 CLI 从这里开始往上找空闲端口;我们保持一致,免得两边的防火墙/白名单各记一份。
PORT_START = 5959
PORT_TRIES = 12
#: 登录窗口活这么久(用户要切到浏览器、扫码/登录、再点授权)。
PENDING_TTL_SECONDS = 180.0
VALIDATE_URL = "https://api.commandcode.ai/alpha/whoami"


class CommandCodeLoginError(ValueError):
    """一句人话:发起不了 / 超时 / 被拒。"""


@dataclass
class _Pending:
    state: str
    profile_id: str
    created: float
    server: ThreadingHTTPServer
    port: int
    api_key: str = ""
    user_name: str = ""
    error: str = ""


@dataclass
class _Store:
    items: dict[str, _Pending] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


_store = _Store()


def _prune() -> None:
    """过期的连服务一起收掉(不关就是一条挂在回环上的口子)。"""
    deadline = time.time() - PENDING_TTL_SECONDS
    for pending_id, entry in list(_store.items.items()):
        if entry.created < deadline:
            _close(entry.server)
            _store.items.pop(pending_id, None)


def _close(server: ThreadingHTTPServer) -> None:
    try:
        server.shutdown()
    except Exception:  # noqa: BLE001 — 关不上只是泄漏一个线程,别连累调用方
        pass
    try:
        server.server_close()
    except Exception:  # noqa: BLE001
        pass


def _clean_key(raw: str) -> str:
    """粘贴来的 Key 常被终端转义序列/空白包住(它的 CLI 也这么洗,见 sanitizeApiKey)。"""
    esc = chr(27)
    text = str(raw or "")
    for noise in (f"{esc}[200~", f"{esc}[201~", "[200~", "[201~"):
        text = text.replace(noise, "")
    return "".join(ch for ch in text if ord(ch) > 31 and ord(ch) != 127).strip()


def validate_key(api_key: str, *, client: Any = None) -> None:
    """拿 `/alpha/whoami` 验一下:401 = Key 不对;别的非 2xx 算「验不了」,也拒 —— 存一个没验过的 Key,
    用户之后要在一轮对话失败时才知道它坏了。"""
    key = _clean_key(api_key)
    if not key:
        raise CommandCodeLoginError("登录没有带回 API Key")
    if client is None:
        import httpx

        client = httpx.Client(timeout=15.0)
        owns = True
    else:
        owns = False
    try:
        response = client.get(VALIDATE_URL, headers={"Authorization": f"Bearer {key}"})
        status = int(getattr(response, "status_code", 0) or 0)
    except Exception as exc:  # noqa: BLE001 — 网络问题:说清楚,不要吞成「Key 错了」
        raise CommandCodeLoginError(f"校验 API Key 时连不上 Command Code:{exc}") from exc
    finally:
        if owns:
            try:
                client.close()
            except Exception:  # noqa: BLE001
                pass
    if status == 401:
        raise CommandCodeLoginError("Command Code 说这个 API Key 无效")
    if not 200 <= status < 300:
        raise CommandCodeLoginError(f"校验 API Key 失败(HTTP {status})")


def _handle_callback(pending_id: str, state: str, payload: dict[str, Any]) -> tuple[int, str]:
    """Studio 的回调:state 对上才收,收到就关服务。返回 (状态码, 给人看的一句)。"""
    entry = _store.items.get(pending_id)
    if entry is None:
        return 404, "这次登录已经失效,请重新发起"
    if not secrets.compare_digest(str(payload.get("state") or ""), entry.state):
        #: 对不上就**什么都不做**:这条口子开着是为了接它自己的回调,不是给别人的。
        entry.error = "回调的 state 对不上,可能是第三方发起的请求"
        return 400, "授权状态不匹配,请在 Mosael 里重新发起登录"
    api_key = _clean_key(str(payload.get("apiKey") or payload.get("api_key") or ""))
    if not api_key:
        entry.error = "Studio 没有带回 API Key"
        return 400, "没有拿到 API Key,请重试"
    entry.api_key = api_key
    entry.user_name = str(payload.get("userName") or payload.get("user_name") or "")
    _close(entry.server)
    return 200, "登录成功,可以回到 Mosael 了"


def start(profile_id: str) -> dict[str, str]:
    """起一个一次性回环服务,返回 {pending_id, url}。调用方负责把 url 打开。"""
    _store.lock.acquire()
    try:
        _prune()
        state = secrets.token_urlsafe(24)
        pending_id = secrets.token_urlsafe(18)
        server = _bind(pending_id, state, profile_id)
        port = int(server.server_address[1])
        _store.items[pending_id] = _Pending(
            state=state, profile_id=profile_id, created=time.time(), server=server, port=port
        )
        threading.Thread(target=server.serve_forever, daemon=True, name="command-code-login").start()
    finally:
        _store.lock.release()
    callback = f"http://127.0.0.1:{port}/callback"
    return {
        "pending_id": pending_id,
        "url": f"{STUDIO_AUTH_URL}?callback={callback}&state={state}",
    }


def _bind(pending_id: str, state: str, profile_id: str) -> ThreadingHTTPServer:
    """在 5959 起挑一个空闲端口绑上(只绑回环)。"""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args: Any) -> None:  # noqa: D401 — 不要往 stdout 打访问日志
            return

        def _reply(self, code: int, message: str) -> None:
            body = json.dumps({"ok": code == 200, "message": message}, ensure_ascii=False).encode("utf-8")
            try:
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                #: 页面是 https(Studio)打的,回环这边给个 CORS 头,好让它读得到结果。
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            except Exception:  # noqa: BLE001
                pass

        def do_OPTIONS(self) -> None:  # noqa: N802 — http.server 的命名
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "content-type")
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.end_headers()

        def do_POST(self) -> None:  # noqa: N802
            if not self.path.startswith("/callback"):
                self._reply(404, "not found")
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length).decode("utf-8", "replace") if length else "{}"
                payload = json.loads(raw or "{}")
                if not isinstance(payload, dict):
                    payload = {}
            except Exception:  # noqa: BLE001
                self._reply(400, "收到的回调不是 JSON")
                return
            code, message = _handle_callback(pending_id, state, payload)
            self._reply(code, message)

    last_error: Exception | None = None
    for offset in range(PORT_TRIES):
        try:
            return ThreadingHTTPServer(("127.0.0.1", PORT_START + offset), Handler)
        except OSError as exc:  # 端口被占:换下一个
            last_error = exc
            continue
    #: 全被占:交回一句人话,让用户手贴 Key(预设里本来就有这个字段)。
    raise CommandCodeLoginError(
        f"本机找不到可用的回调端口({PORT_START}–{PORT_START + PORT_TRIES - 1}),请直接粘贴 API Key"
    ) from last_error


def poll(pending_id: str) -> dict[str, Any]:
    """登录走到哪了:`waiting` / `done`(带一次性的 Key)/ `error`。

    `done` 之后这条 pending 就作废:Key 只交出去一次。
    """
    _store.lock.acquire()
    try:
        _prune()
        entry = _store.items.get(pending_id)
        if entry is None:
            return {"status": "expired"}
        if entry.error:
            message = entry.error
            _close(entry.server)
            _store.items.pop(pending_id, None)
            return {"status": "error", "error": message}
        if entry.api_key:
            key = entry.api_key
            name = entry.user_name
            _store.items.pop(pending_id, None)
            return {"status": "done", "api_key": key, "user_name": name}
        return {"status": "waiting"}
    finally:
        _store.lock.release()


__all__ = ["CommandCodeLoginError", "poll", "start", "validate_key"]
