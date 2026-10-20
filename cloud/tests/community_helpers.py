"""社区分享测试共用的小帮手:起身份、发分享、扫描公开响应。

这些函数只通过 HTTP 走真实链路;断言留在各个测试里。
"""

from __future__ import annotations

from typing import Any

from conftest import api


def identity_body(display_name: str = "Alice", handle: str | None = None) -> dict[str, Any]:
    body: dict[str, Any] = {"display_name": display_name}
    if handle is not None:
        body["handle"] = handle
    return body


def make_identity(client, display_name: str = "Alice", handle: str | None = None) -> dict:
    response = client.put(api("/me"), json=identity_body(display_name, handle))
    assert response.status_code == 200, response.text
    return response.json()["user"]


def share_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "kind": "workflow",
        "title": "Space Opera",
        "summary": "A tiny workflow for testing.",
        "payload": {"version": 1, "nodes": [], "edges": []},
        "license": "CC-BY-4.0",
        # 语言是发布时必须声明的字段(不是服务端猜的):测试默认发中文那一行。
        "locale": "zh-CN",
    }
    body.update(overrides)
    return body


def publish_ok(client, **overrides: Any) -> dict:
    response = client.post(api("/shares"), json=share_body(**overrides))
    assert response.status_code == 201, response.text
    return response.json()["share"]


def leaves(value: Any, path: str = ""):
    """递归展开 JSON,产出 `(path, leaf)`。用来断言"公开响应里没有 email"。"""
    if isinstance(value, dict):
        for key, item in value.items():
            yield from leaves(item, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from leaves(item, f"{path}[{index}]")
    else:
        yield path, value
