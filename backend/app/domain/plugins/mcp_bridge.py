"""MCP 类插件:把一个 MCP server 当插件接进来。

**为什么要有这个**:很多平台已经自己发了 MCP server。在这种情况下,让用户为了用上它去写一个
Python 脚本、把 stdin 的 JSON 翻译成一次 HTTP 调用、再把结果翻译回 stdout —— 那是在重新实现
一个已经存在的东西,而且每加一个端点都要改代码。声明式接进来就够了:

    {
      "id": "...", "name": "...", "version": "1.0.0", "kind": "mcp",
      "mcp": {"transport": "stdio", "command": "npx", "args": ["-y", "@scope/server"]},
      "credentials": [{"key": "SOME_API_KEY", "label": "..."}]
    }

工具清单**从 server 现拉**(扫描时拉一次、缓存进 manifest),不在 manifest 里手抄 —— 手抄的
清单会随 server 升级而烂,而且烂得很安静。这一点和 tikhub 插件不给端点清单是同一个判断。

**进程隔离照旧**:stdio 传输本来就是 spawn 一个子进程,环境同样只有 PATH/HOME/LANG 加上这个
插件自己声明的那几个凭据键。http 传输里 url/headers 支持 `${KEY}` 占位符,因为那些字段进不了
子进程环境。

**为什么每次调用都重连,而不是常驻一个会话**:插件可以随时被停用、改配置、改凭据;常驻会话
意味着要维护"什么时候该重启它"的一整套生命周期,而 MCP 的握手成本在本地是毫秒级。等真出现
握手明显拖慢的场景再谈池化,现在池化只是提前买复杂度。
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Awaitable, Callable, TypeVar

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from app.domain.plugins.manifest import expand

#: 连接 + 握手 + 一次调用的总预算。和进程类插件的 60s 对齐。
MCP_TIMEOUT_SECONDS = 60

T = TypeVar("T")


class McpBridgeError(RuntimeError):
    pass


def is_mcp(manifest: dict[str, Any]) -> bool:
    return str(manifest.get("kind") or "process").strip().lower() == "mcp"


def _spec(manifest: dict[str, Any]) -> dict[str, Any]:
    spec = manifest.get("mcp")
    if not isinstance(spec, dict):
        raise McpBridgeError("MCP 插件必须声明 mcp 配置块(manifest.mcp)")
    return spec


async def _run(manifest: dict[str, Any], env: dict[str, str], fn: Callable[[ClientSession], Awaitable[T]]) -> T:
    spec = _spec(manifest)
    transport = str(spec.get("transport") or "stdio").strip().lower()

    if transport == "stdio":
        command = str(spec.get("command") or "").strip()
        if not command:
            raise McpBridgeError("stdio 传输必须声明 command")
        args = [str(a) for a in (spec.get("args") or []) if str(a).strip()]
        # 子进程环境:最小集 + 该插件自己的凭据。与进程类插件同一条规矩。
        child_env = {
            "PATH": os.environ.get("PATH", ""),
            "HOME": os.environ.get("HOME", ""),
            "LANG": os.environ.get("LANG", "en_US.UTF-8"),
            "MOSAEL_PLUGIN": "1",
            **env,
        }
        params = StdioServerParameters(
            command=command, args=args, env=child_env, cwd=str(manifest.get("_path") or "") or None
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)

    if transport in ("http", "streamable-http"):
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client

        url = expand(str(spec.get("url") or "").strip(), env)
        if not url:
            raise McpBridgeError("http 传输必须声明 url")
        headers = {str(k): expand(str(v), env) for k, v in (spec.get("headers") or {}).items()}
        async with create_mcp_http_client(headers=headers or None) as http_client:
            async with streamable_http_client(url, http_client=http_client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await fn(session)

    raise McpBridgeError(f"不支持的 MCP 传输方式: {transport}(支持 stdio / http)")


def _sync(manifest: dict[str, Any], env: dict[str, str], fn: Callable[[ClientSession], Awaitable[T]]) -> T:
    """在自己的事件循环里跑一次。调用方是同步的(FastAPI 的同步端点在线程池里,
    工作流引擎也在线程里),所以这里可以直接 asyncio.run。"""
    try:
        return asyncio.run(asyncio.wait_for(_run(manifest, env, fn), timeout=MCP_TIMEOUT_SECONDS))
    except McpBridgeError:
        raise
    except asyncio.TimeoutError as exc:
        raise McpBridgeError(f"MCP 插件响应超时({MCP_TIMEOUT_SECONDS}s)") from exc
    except Exception as exc:  # noqa: BLE001 — 传输层的异常五花八门,统一成一句能看懂的
        raise McpBridgeError(f"连接 MCP 插件失败: {type(exc).__name__}: {exc}"[:400]) from exc


def discover_tools(manifest: dict[str, Any], env: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """向 server 要一次工具清单,转成 manifest.tools 的形状。"""

    async def _list(session: ClientSession) -> list[dict[str, Any]]:
        result = await session.list_tools()
        return [
            {
                "name": tool.name,
                # MCP Tool.title 是给人看的名字；name 是机器调用用的稳定标识。两者不能互相
                # 顶替，否则节点面板会把 bilibili_web_fetch_one_video 当成产品文案。
                "title": tool.title or "",
                "description": tool.description or "",
                # mcp 2.0 起字段名统一为 snake_case(原 inputSchema)。
                "input_schema": tool.input_schema or {"type": "object", "properties": {}},
            }
            for tool in result.tools
        ]

    return _sync(manifest, env or {}, _list)


def call_tool(manifest: dict[str, Any], tool_name: str, payload: dict[str, Any], env: dict[str, str]) -> dict[str, Any]:
    """调一次工具。返回值统一成 dict —— 插件调用记录那张表存的是 JSON 对象。"""

    async def _call(session: ClientSession) -> dict[str, Any]:
        result = await session.call_tool(tool_name, payload)
        # mcp 2.0 起字段名统一为 snake_case(原 isError / structuredContent)。
        if getattr(result, "is_error", False):
            raise McpBridgeError(_text(result) or f"MCP 工具 {tool_name} 返回错误")
        # structured_content 是 MCP 后来加的结构化返回;有就用它,没有就把文本块拼起来。
        structured = getattr(result, "structured_content", None)
        if isinstance(structured, dict):
            return structured
        # 没有 output_schema 的工具(大多数)只回文本块,而那段文本往往本身就是 JSON。
        # 解出来给调用方,而不是塞一个 {"text": "{...}"} —— 后者让工作流的 {{变量}} 引用和
        # 模型的下一步都得先自己再解一层。
        text = _text(result)
        try:
            parsed = json.loads(text)
        except (ValueError, TypeError):
            return {"text": text}
        return parsed if isinstance(parsed, dict) else {"text": text}

    return _sync(manifest, env, _call)


def _text(result: Any) -> str:
    parts = [getattr(block, "text", "") for block in (getattr(result, "content", None) or [])]
    return "\n".join(part for part in parts if part).strip()


__all__ = ["MCP_TIMEOUT_SECONDS", "McpBridgeError", "call_tool", "discover_tools", "is_mcp"]
