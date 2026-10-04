"""智能体的浏览器工具也认「在框架里」:元素在页面里某个同源 iframe 里时,填那个框架的选择器。

和工作流节点同一件事、同一份实现:工具只把 `frame` 原样交给执行器(和节点交的是同一个参数),找框架、
判跨域、等框架出现、报错的原话都在执行器那边(electron/publish/browserActions.ts + pageDriver.inFrame)。
这里钉的是接线:六个按选择器操作的工具都收这个参数、交得过去;没填就不交(整个页面,和以前一样)。
"""
from __future__ import annotations

import asyncio
import contextvars

import mcp_server
from app.core.db import SessionLocal
from app.core.security import find_session
from app.domain import browser as bdom
from tests.util import fresh_client

FRAME = "iframe#editor"

#: 工具 → 一份最小参数(不含 frame)、它交给执行器的动作名。
TOOLS = {
    "browser_click": ({"selector": "#go"}, "click"),
    "browser_type": ({"selector": "#q", "value": "hi"}, "input"),
    "browser_read": ({"selector": "h1"}, "extract"),
    "browser_wait": ({"selector": "#ready", "timeout_ms": 1000}, "wait"),
    "browser_scroll": ({"selector": "#more"}, "scroll"),
}


def _setup(monkeypatch) -> tuple[str, str]:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        caller = find_session(db, client.headers["Authorization"].removeprefix("Bearer ")).user_id
        sid = bdom.open_session(db, workspace_id=ws, actor=caller).id
        db.commit()
    monkeypatch.setattr(mcp_server, "_CALLER_ID", contextvars.ContextVar("test_caller", default=caller))
    return ws, sid


def test_按选择器操作的工具都把框架交给执行器(monkeypatch) -> None:
    ws, sid = _setup(monkeypatch)
    calls: list = []
    monkeypatch.setattr(bdom, "run_action", lambda s, action, args, **k: (calls.append((action, args)) or {"value": ""}))
    for name, (args, action) in TOOLS.items():
        calls.clear()
        getattr(mcp_server, name)(session_id=sid, workspace_id=ws, frame=f"  {FRAME} ", **args)
        assert calls and calls[0][0] == action, name
        assert calls[0][1]["frame"] == FRAME, f"{name} 没把框架交给执行器:{calls[0][1]}"


def test_没填框架就不交_和以前一样作用在整个页面(monkeypatch) -> None:
    ws, sid = _setup(monkeypatch)
    calls: list = []
    monkeypatch.setattr(bdom, "run_action", lambda s, action, args, **k: (calls.append(args) or {"value": ""}))
    for name, (args, _action) in TOOLS.items():
        calls.clear()
        getattr(mcp_server, name)(session_id=sid, workspace_id=ws, **args)
        assert "frame" not in calls[0], name


def test_上传也认框架(monkeypatch) -> None:
    ws, sid = _setup(monkeypatch)
    seen: dict = {}

    from app.domain import host_files

    monkeypatch.setattr(host_files, "upload_source", lambda db, **kwargs: object())
    monkeypatch.setattr(bdom, "upload_file", lambda session_id, file, **kwargs: (seen.update(kwargs) or {}))
    mcp_server.browser_upload(session_id=sid, selector="input[type=file]", asset_id="a1", workspace_id=ws, frame=FRAME)
    assert seen["frame"] == FRAME
    seen.clear()
    mcp_server.browser_upload(session_id=sid, selector="input[type=file]", asset_id="a1", workspace_id=ws)
    assert seen["frame"] == ""


def test_工具说明里写清楚什么时候用框架() -> None:
    tools = {tool.name: tool for tool in asyncio.run(mcp_server.mcp.list_tools())}
    for name in [*TOOLS, "browser_upload"]:
        schema = tools[name].input_schema["properties"]
        assert "frame" in schema, f"{name} 没有 frame 参数"
    assert "iframe" in tools["browser_click"].description
