"""智能体工具的 HTTP 通道(/api/agent/tools/{name})只跑登记过的工具(SEC-13)。

此前分发是 `getattr(mcp_server 模块, name)`,只排除下划线开头的名字:模块里任何公开的可调用对象 —— `Any`、`MCPServer`、
`calling_as`、`set_requested_by`,以及以后哪天多 import 进来的一个函数 —— 都成了任何登录用户能调、不经确认卡的「工具」。
"""

from __future__ import annotations

import inspect

import mcp_server
from tests.util import fresh_client


def _not_tools() -> list[str]:
    """模块里公开、可调用、却不是登记过的工具的那些名字。"""
    return sorted(
        name for name, value in vars(mcp_server).items()
        if not name.startswith("_") and callable(value) and name not in mcp_server.REGISTERED_TOOLS
    )


def test_模块里不是工具的可调用对象_一个都调不到() -> None:
    client = fresh_client()
    names = _not_tools()
    assert {"calling_as", "set_requested_by", "MCPServer", "Any"} <= set(names), "模拟成立:这些名字确实在模块里"

    reachable = [name for name in names if client.post(f"/api/agent/tools/{name}", json={"arguments": {}}).status_code != 404]

    assert reachable == [], f"这些不是工具,却能经 HTTP 通道调:{reachable}"


def test_登记过的工具照常能调() -> None:
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})

    response = client.post("/api/agent/tools/list_workspaces", json={"arguments": {}})

    assert response.status_code == 200, response.text
    assert [one["name"] for one in response.json()["result"]] == ["W"]


def test_登记过的工具都是模块里的同名函数() -> None:
    """通道按名字取函数:登记表里的每个名字在模块里都得有一个真的函数。"""
    missing = [name for name in mcp_server.REGISTERED_TOOLS if not inspect.isfunction(getattr(mcp_server, name, None))]
    assert missing == []
    assert len(mcp_server.REGISTERED_TOOLS) >= 100
