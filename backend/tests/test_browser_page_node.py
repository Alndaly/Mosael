"""工作流「切换页面」节点:会话里开着几个页面时切到某一页,或关掉当前页。

页面本身在执行器那一侧(electron/publish/actionPage.ts + accountViews 的页面列表);这里钉后端这一半:
节点把「切 / 关、按什么找、找什么」交给执行器,交出现在这一页的网址、标题和页数;登记齐全;智能体也有。
"""
from __future__ import annotations

import types

from app.core.db import SessionLocal
from app.domain import browser as bdom
from app.domain.workflows import NODE_TYPES
from app.domain.workflows.executors import browser as bx
from tests.util import fresh_client


def _workspace() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _wf(ws: str):
    return types.SimpleNamespace(workspace_id=ws, id="wf-test")


def _run_node(monkeypatch, config: dict, result: dict) -> tuple[dict, dict]:
    seen: dict = {}

    def fake(sid, action, args, **kwargs):
        seen.update(action=action, args=args)
        return result

    monkeypatch.setattr(bdom, "run_action", fake)
    ws = _workspace()
    with SessionLocal() as db:
        sid = bdom.open_session(db, workspace_id=ws, actor=None).id
        out = bx.browser_page(db, _wf(ws), {"session": sid, **config})
    return out, {**seen, "sid": sid}


def test_切到某一页_交出这一页的网址标题和页数(monkeypatch) -> None:
    out, seen = _run_node(
        monkeypatch,
        {"operation": "switch", "by": "title", "value": "创作中心"},
        {"value": {"index": 2, "title": "创作中心", "url": "https://creator.example.com/", "count": 3}},
    )
    assert seen["action"] == "page"
    assert seen["args"] == {
        "operation": "switch", "by": "title", "value": "创作中心", "origin": {"run": "", "node": ""},
    }
    assert out == {"session": seen["sid"], "url": "https://creator.example.com/", "title": "创作中心", "count": 3}


def test_关掉当前页不带找页的参数(monkeypatch) -> None:
    out, seen = _run_node(
        monkeypatch,
        {"operation": "close", "by": "index", "value": "2"},
        {"value": {"index": 1, "title": "首页", "url": "https://example.com/", "count": 1}},
    )
    assert seen["args"] == {"operation": "close", "origin": {"run": "", "node": ""}}
    assert out["count"] == 1 and out["url"] == "https://example.com/"


def test_没写做什么就是切页_按什么找认不出就按第几个(monkeypatch) -> None:
    _, seen = _run_node(monkeypatch, {"by": "color", "value": "1"}, {"value": {}})
    assert seen["args"]["operation"] == "switch"
    assert seen["args"]["by"] == "index"


def test_切换页面节点登记齐全_切页时要说找哪一页() -> None:
    spec = NODE_TYPES["browser_page"]
    assert spec["category"] == "wfCat_browser" and spec["external"] is True
    assert spec["outputs"] == ["session", "url", "title", "count"]
    assert spec["config"]["operation"]["options"] == ["switch", "close"]
    assert spec["config"]["value"]["required"] is True
    assert spec["config"]["value"]["active_when"] == {"operation": "switch"}
    assert spec["config"]["by"]["active_when"] == {"operation": "switch"}
    assert "page" in bdom.KNOWN_ACTIONS


def test_智能体也能切页() -> None:
    import asyncio

    import mcp_server

    assert "browser_page" in {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
