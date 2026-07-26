"""Phase 2:智能体浏览器工具。browser_open 走确认卡(用户看到网址再放行),其余动作内联;
入口确认 + 会话归属校验是安全边界。真正的浏览器往返由 Electron 执行器负责,这里只验证接线。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import BrowserSession
from app.domain import browser
from tests.util import fresh_client

BROWSER_TOOLS = [
    "browser_open", "browser_navigate", "browser_click", "browser_type",
    "browser_read", "browser_wait", "browser_close",
]


def _ws(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_browser_tools_in_manifest_and_gating() -> None:
    client = fresh_client()
    by_name = {t["name"]: t for t in client.get("/api/agent/tools").json()}
    for name in BROWSER_TOOLS:
        assert name in by_name, f"{name} 不在工具清单"
    assert by_name["browser_open"]["confirmation"] is True  # 入口走确认卡
    assert by_name["browser_navigate"]["confirmation"] is False  # 同会话动作内联
    assert by_name["browser_read"]["confirmation"] is False


def test_browser_open_confirmation_opens_agent_session() -> None:
    client = fresh_client()
    ws = _ws(client)
    conf = client.post(
        "/api/confirmations",
        json={"workspace_id": ws, "tool": "browser_open", "payload": {"url": "", "session_mode": "ephemeral"}},
    ).json()
    assert conf["status"] == "pending"
    assert "打开" in conf["summary"] and "浏览器" in conf["summary"]

    approved = client.post(f"/api/confirmations/{conf['id']}/approve").json()
    assert approved["status"] == "executed"
    sid = approved["result"]["session_id"]
    with SessionLocal() as db:
        session = db.get(BrowserSession, sid)
        assert session is not None and session.owner_kind == "agent"
        assert session.partition == f"ephemeral-{sid}"  # 隔离,非 persist:mibu-*


def test_browser_open_rejects_non_http_url() -> None:
    client = fresh_client()
    ws = _ws(client)
    r = client.post(
        "/api/confirmations",
        json={"workspace_id": ws, "tool": "browser_open", "payload": {"url": "ftp://evil"}},
    )
    assert r.status_code == 422  # ConfirmationError → 只能 http(s)


def test_agent_browser_act_enforces_ownership() -> None:
    client = fresh_client()
    ws = _ws(client)
    with SessionLocal() as db:
        sid = browser.open_session(db, workspace_id=ws).id

    # 不存在的会话 → 404(在跑动作之前就挡下)
    assert client.post(
        "/api/agent-browser/act",
        json={"workspace_id": ws, "session_id": "nope", "action": "navigate", "args": {}},
    ).status_code == 404

    # 会话属于别的工作区 → 404
    ws2 = client.post("/api/workspaces", json={"name": "W2"}).json()["id"]
    assert client.post(
        "/api/agent-browser/act",
        json={"workspace_id": ws2, "session_id": sid, "action": "navigate", "args": {}},
    ).status_code == 404
