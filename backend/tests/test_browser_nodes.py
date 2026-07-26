"""RPA 浏览器节点:登记齐全 + 执行器把动作正确交给 run_action(用 monkeypatch 替掉真执行器)。"""

from __future__ import annotations

import types

import pytest

from app.core.db import SessionLocal
from app.db.models import BrowserSession, Workspace
from app.domain import browser as bdom
from app.domain.workflows import NODE_TYPES
from app.domain.workflows.executors import browser as bx, registered_types
from tests.util import fresh_client

BROWSER_NODES = [
    "browser_open", "browser_navigate", "browser_click", "browser_input",
    "browser_extract", "browser_wait", "browser_scroll", "browser_evaluate", "browser_close",
]


def _workspace_id() -> str:
    client = fresh_client()
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _wf(ws: str):
    return types.SimpleNamespace(workspace_id=ws, id="wf-test")


def test_browser_nodes_registered_and_categorized() -> None:
    for t in BROWSER_NODES:
        assert t in NODE_TYPES, f"{t} 未登记 NODE_TYPES"
        assert t in registered_types(), f"{t} 无执行器"
        assert NODE_TYPES[t].get("category") == "浏览器"


def test_browser_open_navigates_and_returns_session(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(bdom, "run_action", lambda sid, action, args, **k: (calls.append((action, args)) or {}))
    ws = _workspace_id()
    with SessionLocal() as db:
        out = bx.browser_open(db, _wf(ws), {"url": "https://x.test"})
        sid = out["session"]
        assert sid  # 真的建了会话(隔离分区)
        assert db.get(BrowserSession, sid).partition == f"ephemeral-{sid}"
    assert calls == [("navigate", {"url": "https://x.test"})]


def test_browser_extract_returns_value(monkeypatch) -> None:
    monkeypatch.setattr(bdom, "run_action", lambda sid, action, args, **k: {"value": "Hello"})
    ws = _workspace_id()
    with SessionLocal() as db:
        sid = bx.browser_open(db, _wf(ws), {})["session"]
        out = bx.browser_extract(db, _wf(ws), {"session": sid, "selector": "h1"})
    assert out == {"session": sid, "value": "Hello"}


def test_browser_click_passes_text_and_exact(monkeypatch) -> None:
    seen: dict = {}
    monkeypatch.setattr(bdom, "run_action", lambda sid, action, args, **k: (seen.update({"action": action, "args": args}) or {}))
    ws = _workspace_id()
    with SessionLocal() as db:
        bx.browser_click(db, _wf(ws), {"session": "s1", "text": "登录", "exact": "是"})
    assert seen["action"] == "click"
    assert seen["args"]["text"] == "登录" and seen["args"]["exact"] is True


def test_browser_node_without_session_errors() -> None:
    ws = _workspace_id()
    with SessionLocal() as db:
        with pytest.raises(Exception) as ei:
            bx.browser_navigate(db, _wf(ws), {"url": "https://x.test"})
    assert "浏览器会话" in str(ei.value)


def test_browser_wait_needs_a_target(monkeypatch) -> None:
    monkeypatch.setattr(bdom, "run_action", lambda *a, **k: {})
    ws = _workspace_id()
    with SessionLocal() as db:
        with pytest.raises(Exception):
            bx.browser_wait(db, _wf(ws), {"session": "s1"})  # 无 selector/url_contains/text
