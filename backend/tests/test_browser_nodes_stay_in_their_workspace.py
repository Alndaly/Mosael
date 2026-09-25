"""浏览器节点只能动**本工作区**的浏览器会话。

session 常常来自上游节点(`{{打开浏览器.session}}`),而上游 —— 一段代码、一次 HTTP 返回 ——
拿得到任何地方的 id。此前除「打开浏览器」之外的九个节点拿到 id 就把动作交给 run_action,
而 run_action 不认识工作区:A 工作区的工作流能在 B 工作区某人已登录的池档案会话里
`evaluate` 出 cookie、`click` 发布按钮,或者直接把它关掉。

智能体那条路一直是挡着的(api/routes/agent_browser._verify 每次核对 workspace_id),
漏的只有工作流这一条。
"""

from __future__ import annotations

import types

import pytest

from app.core.db import SessionLocal
from app.db.models import BrowserSession
from app.domain import browser as bdom
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import browser as bx
from tests.util import fresh_client


def _two_workspaces() -> tuple[str, str]:
    client = fresh_client()
    a = client.post("/api/workspaces", json={"name": "A"}).json()["id"]
    b = client.post("/api/workspaces", json={"name": "B"}).json()["id"]
    return a, b


def _wf(ws: str):
    return types.SimpleNamespace(workspace_id=ws, id="wf-test")


@pytest.mark.parametrize(
    ("node", "config"),
    [
        ("browser_navigate", {"url": "https://x.test"}),
        ("browser_click", {"selector": ".publish"}),
        ("browser_input", {"selector": "#q", "value": "v"}),
        ("browser_extract", {"selector": "h1"}),
        ("browser_wait", {"selector": "h1"}),
        ("browser_scroll", {}),
        ("browser_evaluate", {"expression": "document.cookie"}),
        ("browser_upload", {"selector": "input", "file_path": "/tmp/x.mp4"}),
    ],
)
def test_别的工作区的会话不能拿来跑动作(monkeypatch, node: str, config: dict) -> None:
    calls: list = []
    monkeypatch.setattr(bdom, "run_action", lambda sid, action, args, **k: (calls.append(action) or {}))
    a, b = _two_workspaces()
    with SessionLocal() as db:
        foreign = bdom.open_session(db, workspace_id=a, actor=None).id
        with pytest.raises(WorkflowDomainError):
            getattr(bx, node)(db, _wf(b), {"session": foreign, **config})
    assert calls == [], f"{node} 把动作交给了别的工作区的会话:{calls}"


def test_别的工作区的会话不能拿来关(monkeypatch) -> None:
    monkeypatch.setattr(bdom, "run_action", lambda *a, **k: {})
    a, b = _two_workspaces()
    with SessionLocal() as db:
        foreign = bdom.open_session(db, workspace_id=a, actor=None).id
        with pytest.raises(WorkflowDomainError):
            bx.browser_close(db, _wf(b), {"session": foreign})
    with SessionLocal() as db:
        assert db.get(BrowserSession, foreign).status == "open", "B 的工作流把 A 的会话关掉了"


def test_本工作区的会话照常用(monkeypatch) -> None:
    calls: list = []
    monkeypatch.setattr(bdom, "run_action", lambda sid, action, args, **k: (calls.append((sid, action)) or {}))
    a, _ = _two_workspaces()
    with SessionLocal() as db:
        sid = bdom.open_session(db, workspace_id=a, actor=None).id
        assert bx.browser_click(db, _wf(a), {"session": sid, "selector": ".go"}) == {"session": sid}
        bx.browser_close(db, _wf(a), {"session": sid})
    assert calls == [(sid, "click")]
    with SessionLocal() as db:
        assert db.get(BrowserSession, sid).status == "closed"
