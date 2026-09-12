"""RPA 浏览器节点:登记齐全 + 执行器把动作正确交给 run_action(用 monkeypatch 替掉真执行器)。"""

from __future__ import annotations

import types

import pytest

from app.core.db import SessionLocal
from app.db.models import BrowserSession
from app.domain import browser as bdom
from app.domain.workflows import NODE_TYPES, WorkflowDomainError
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
        assert NODE_TYPES[t].get("category") == "wfCat_browser"


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
        with pytest.raises(WorkflowDomainError, match="selector / url_contains / text"):
            bx.browser_wait(db, _wf(ws), {"session": "s1"})  # 无 selector/url_contains/text


class Test失败现场:
    """一步失败之后,人要能看出**当时页面是什么样**。

    「等待超时」是站点改版后最常撞见的那条错误。错误文案已经能说清等的是什么、等了多久、
    当时停在哪一页(1d33ab27),但光有网址还是不够:那一刻屏幕上是登录墙、是验证码,还是
    页面压根没跳过去?一张图能省掉「把节点配置重贴一遍、手动复现一次」那整个来回。
    """

    @staticmethod
    def _fake(monkeypatch, *, shot):
        """真动作一律失败;截图按 shot 给的行为来。"""
        def run_action(sid, action, args, **kwargs):
            if action == "screenshot":
                return shot() if callable(shot) else shot
            raise bdom.BrowserDomainError("等待超时(15.0s):元素始终没有出现 #login")
        monkeypatch.setattr(bdom, "run_action", run_action)

    def test_失败时带上截图和当时的网址(self, monkeypatch) -> None:
        monkeypatch.setattr(bdom, "run_action", lambda sid, a, args, **k: {})
        ws = _workspace_id()
        with SessionLocal() as db:
            sid = bx.browser_open(db, _wf(ws), {})["session"]
        self._fake(monkeypatch, shot={"value": "data:image/png;base64,AAAA", "lastUrl": "https://x.test/login"})
        with SessionLocal() as db:
            with pytest.raises(WorkflowDomainError) as caught:
                bx.browser_wait(db, _wf(ws), {"session": sid, "selector": "#login", "timeout_ms": 15000})
        details = caught.value.details
        assert details["screenshot"] == "data:image/png;base64,AAAA"
        assert details["page_url"] == "https://x.test/login"
        # 现场还要说清这一步在做什么、在找什么 —— 光有图仍然要回去翻节点配置。
        assert details["action"] == "wait" and details["selector"] == "#login"

    def test_截不到图也不能让取证变成第二次失败(self, monkeypatch) -> None:
        """会话已经关掉、执行器没响应…… 都只意味着"这次没有图",原来的失败照样往上抛。"""
        monkeypatch.setattr(bdom, "run_action", lambda sid, a, args, **k: {})
        ws = _workspace_id()
        with SessionLocal() as db:
            sid = bx.browser_open(db, _wf(ws), {})["session"]

        def boom():
            raise bdom.BrowserDomainError("浏览器会话不存在或已关闭")

        self._fake(monkeypatch, shot=boom)
        with SessionLocal() as db:
            with pytest.raises(WorkflowDomainError, match="等待超时"):
                bx.browser_wait(db, _wf(ws), {"session": sid, "selector": "#login"})

    def test_过大的图不往任务记录里塞(self, monkeypatch) -> None:
        """失败记录进的是任务总线的 payload。截图已经在执行器侧缩到 480 宽,这道闸防的是意外。"""
        monkeypatch.setattr(bdom, "run_action", lambda sid, a, args, **k: {})
        ws = _workspace_id()
        with SessionLocal() as db:
            sid = bx.browser_open(db, _wf(ws), {})["session"]
        huge = "data:image/png;base64," + "A" * (bx._SHOT_MAX_CHARS + 1)
        self._fake(monkeypatch, shot={"value": huge, "lastUrl": "https://x.test/"})
        with SessionLocal() as db:
            with pytest.raises(WorkflowDomainError) as caught:
                bx.browser_click(db, _wf(ws), {"session": sid, "selector": ".go"})
        details = caught.value.details
        assert "screenshot" not in details
        # 图没了,别的现场还在 —— 这才是"尽力而为"该有的样子。
        assert details["page_url"] == "https://x.test/" and details["selector"] == ".go"
