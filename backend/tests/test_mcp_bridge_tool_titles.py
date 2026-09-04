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
