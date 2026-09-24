from __future__ import annotations

import asyncio
from types import SimpleNamespace


def test_mcp_发现保留给人看的_tool_title(monkeypatch) -> None:
    """MCP 同时定义 name(调用协议) 和 title(展示文案)，发现层不得丢后者。"""
    from app.domain.plugins import mcp_bridge

    tool = SimpleNamespace(
        name="fetch_one_video",
        title="获取单个视频",
        description="读取视频详情",
        input_schema={"type": "object", "properties": {}},
    )

    class Session:
        async def list_tools(self):
            return SimpleNamespace(tools=[tool])

    def run(_manifest, _env, fn):
        return asyncio.run(fn(Session()))

    monkeypatch.setattr(mcp_bridge, "_sync", run)
    discovered = mcp_bridge.discover_tools({"kind": "mcp", "mcp": {}})

    assert discovered == [
        {
            "name": "fetch_one_video",
            "title": "获取单个视频",
            "description": "读取视频详情",
            "input_schema": {"type": "object", "properties": {}},
        }
    ]


def test_调用方给的预算原样用在这一次_mcp_调用上(monkeypatch) -> None:
    """plugins.tools.invoke 会把 timeout 传下来(Blender 取回场景要等得更久);MCP 这一层此前
    不收这个参数,每一次带预算的调用都在发请求前就报 unexpected keyword argument。"""
    from app.domain.plugins import mcp_bridge

    class Session:
        async def call_tool(self, name, arguments):
            return SimpleNamespace(is_error=False, structured_content={"ok": name, **arguments}, content=[])

    seen: list[float] = []

    def run(_manifest, _env, fn, timeout=mcp_bridge.MCP_TIMEOUT_SECONDS):
        seen.append(timeout)
        return asyncio.run(fn(Session()))

    monkeypatch.setattr(mcp_bridge, "_sync", run)
    assert mcp_bridge.call_tool({"kind": "mcp", "mcp": {}}, "scene", {"a": 1}, {}, timeout=300) == {"ok": "scene", "a": 1}
    assert mcp_bridge.call_tool({"kind": "mcp", "mcp": {}}, "scene", {}, {}) == {"ok": "scene"}
    assert seen == [300, mcp_bridge.MCP_TIMEOUT_SECONDS]
