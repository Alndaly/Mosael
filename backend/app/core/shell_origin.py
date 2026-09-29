"""本机桌面后端只放行**带着壳令牌**的 `Origin: null`。

打包版界面从 file:// 加载,发出的跨源请求 Origin 是 `null`。可 `null` 不只属于它:任何网页里的 sandboxed iframe、
data: 文档的 Origin 也是 `null`。CORS 白名单里写着 `null`,就等于允许任何网页读回本机后端的响应 —— 首次运行
时它能抢先注册管理员并读回令牌,开放注册时能给自己开个号。

所以桌面版(`MOSAEL_LOCAL_DESKTOP`)在 CORS 之前加一道:Origin 是 `null` 的请求必须带 `X-Mosael-Shell`,值是
主密钥派生的壳令牌(HMAC-SHA256(主密钥, "mosael-shell-origin"))。Electron 主进程在自己发往本机后端的请求上
加这个头(electron/master-key.cjs 的 shellToken + main.cjs 的 installShellHeader),网页算不出它。

团队服务器不在这道之下:那里的 Electron 客户端算不出服务器的主密钥,而服务器的 CORS 名单由部署者配置。
"""

from __future__ import annotations

import hashlib
import hmac

from starlette.types import ASGIApp, Receive, Scope, Send

SHELL_HEADER = "x-mosael-shell"


def shell_token() -> str:
    from app.core.secrets_at_rest import master_key

    return hmac.new(master_key(), b"mosael-shell-origin", hashlib.sha256).hexdigest()


class ShellOriginGuard:
    """Origin 为 `null` 而没带对壳令牌的请求一律 403,包括 CORS 预检 —— 连「能不能发」都不告诉它。"""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope["headers"]}
            if headers.get("origin") == "null" and not hmac.compare_digest(headers.get(SHELL_HEADER, ""), shell_token()):
                await send({"type": "http.response.start", "status": 403,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"detail":"Origin null is only accepted from the Mosael shell"}'})
                return
        await self.app(scope, receive, send)


__all__ = ["SHELL_HEADER", "ShellOriginGuard", "shell_token"]
