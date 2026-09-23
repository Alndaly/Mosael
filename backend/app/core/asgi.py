"""纯 ASGI 中间件共用的小工具。中间件为什么一律写成纯 ASGI,见 app/api/middleware。"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from starlette.datastructures import MutableHeaders
from starlette.types import Message, Send


def adding_headers(send: Send, headers: Callable[[], Mapping[str, str]]) -> Send:
    """包一层 send:响应头发出去的那一刻,补上 `headers()` 给的那几个。

    用函数而不是现成的字典:有的头要等处理完才知道(建了几个任务)。
    """

    async def send_with_headers(message: Message) -> None:
        if message["type"] == "http.response.start":
            extra = headers()
            if extra:
                target = MutableHeaders(scope=message)
                for name, value in extra.items():
                    target[name] = value
        await send(message)

    return send_with_headers
