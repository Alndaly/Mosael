"""工作流「截图」节点:截自动化会话里那一页,直接存进素材库,输出素材 id。

截图本身在执行器那一侧(electron/publish/actionCapture.ts,和顶栏「截屏」同一份实现),这里钉的是后端这一半:

- 节点把截哪种、截哪个元素、等多久、叫什么,连同「哪次运行、哪个节点」交给执行器,交回素材 id;
- 执行器交来的截图经产物入口入库:只收图片、出处种类只认节点截得出来的那三种、记下运行 / 节点 / 会话;
- 节点登记齐全(元素模式下选择器必填),智能体也有同一件事(browser_screenshot)。
"""
from __future__ import annotations

import io
import types

from PIL import Image

from app.core.db import SessionLocal
from app.db.models import Asset, BrowserAction
from app.domain import browser as bdom
from app.domain.workflows import NODE_TYPES
from app.domain.workflows.executors import browser as bx
from app.domain.workflows.run_scope import node_scope
from tests.util import fresh_client, worker_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _png(width: int = 80, height: int = 50) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (40, 160, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def _wf(ws: str):
    return types.SimpleNamespace(workspace_id=ws, id="wf-test")


def _running_capture(workspace_id: str, origin: dict | None = None) -> tuple[dict, str]:
    with SessionLocal() as db:
        session_id = bdom.open_session(db, workspace_id=workspace_id, actor=None).id
        db.add(BrowserAction(
            session_id=session_id, workspace_id=workspace_id, action="capture",
            args={"mode": "full", **({"origin": origin} if origin else {})}, status="queued",
        ))
        db.commit()
    action = worker_client().post("/api/browser/worker/claim", json={"worker": "test"}).json()["action"]
    assert action is not None and action["action"] == "capture"
    return action, session_id


def _shot(action: dict, data: bytes, **fields):
    form = {
        "lease_token": action["lease_token"],
        "kind": "screenshot",
        "filename": "screenshot.png",
        "capture": "screenshot_full",
        "name": "",
        "page_url": "https://example.com/post/1",
        "page_title": "一篇帖子",
        "captured_at": "2026-10-04T05:30:00.000Z",
        **fields,
    }
    return worker_client().post(
        f"/api/browser/worker/actions/{action['id']}/artifact", data=form,
        files={"file": ("screenshot.png", data, "image/png")},
    )


# ---------- 节点 ----------


def test_截图节点把截法连同运行和节点交给执行器_交回素材id(monkeypatch) -> None:
    seen: dict = {}

    def fake(sid, action, args, **kwargs):
        seen.update(action=action, args=args)
        return {"value": {"asset_id": "shot-1", "width": 2560, "height": 1600, "truncated": False}}

    monkeypatch.setattr(bdom, "run_action", fake)
    client = fresh_client()
    ws = _workspace(client)
    with SessionLocal() as db:
        sid = bdom.open_session(db, workspace_id=ws, actor=None).id
        with node_scope("n_shot"):
            out = bx.browser_screenshot(
                db, _wf(ws), {"session": sid, "mode": "element", "selector": ".cover", "name": "封面", "wait_ms": 800},
            )
    assert out == {"session": sid, "asset_id": "shot-1"}
    assert seen["action"] == "capture"
    assert seen["args"] == {
        "mode": "element", "selector": ".cover", "name": "封面", "wait_ms": 800,
        "origin": {"run": "", "node": "n_shot"},
    }


def test_截图节点没写截法就截可见区域(monkeypatch) -> None:
    seen: dict = {}
    monkeypatch.setattr(bdom, "run_action", lambda sid, action, args, **k: (seen.update(args=args) or {"value": {}}))
    client = fresh_client()
    ws = _workspace(client)
    with SessionLocal() as db:
        sid = bdom.open_session(db, workspace_id=ws, actor=None).id
        out = bx.browser_screenshot(db, _wf(ws), {"session": sid, "mode": "everything"})
    assert seen["args"]["mode"] == "visible"
    assert out["asset_id"] == ""


def test_截图节点登记齐全_元素模式下选择器必填() -> None:
    spec = NODE_TYPES["browser_screenshot"]
    assert spec["category"] == "wfCat_browser" and spec["external"] is True
    assert spec["outputs"] == ["session", "asset_id"]
    assert spec["config"]["mode"]["options"] == ["visible", "full", "element"]
    assert spec["config"]["selector"]["required"] is True
    assert spec["config"]["selector"]["active_when"] == {"mode": "element"}
    assert "capture" in bdom.KNOWN_ACTIONS


# ---------- 执行器交来的截图 ----------


def test_截图入库_记下出处与是哪次运行哪个节点() -> None:
    client = fresh_client()
    ws = _workspace(client)
    action, session_id = _running_capture(ws, origin={"run": "job-9", "node": "n_shot"})
    response = _shot(action, _png(), name="封面参考")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "image" and body["name"] == "封面参考"
    with SessionLocal() as db:
        asset = db.get(Asset, body["asset_id"])
        assert asset.workspace_id == ws
        assert asset.source == "captured"
        info = asset.media_info
    assert info["capture"] == "screenshot_full"
    assert info["source_page_url"] == "https://example.com/post/1"
    assert info["source_page_title"] == "一篇帖子"
    assert info["source_run_id"] == "job-9"
    assert info["source_node_id"] == "n_shot"
    assert info["source_browser_session_id"] == session_id
    assert info["width"] == 80 and info["height"] == 50
    assert "source_url" not in info  # 截图不冒充「从某个地址下下来的文件」


def test_截图没起名就用页面标题() -> None:
    client = fresh_client()
    ws = _workspace(client)
    action, _ = _running_capture(ws)
    response = _shot(action, _png(), capture="screenshot_element")
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "一篇帖子"


def test_截图入口只收图片_出处种类有数() -> None:
    client = fresh_client()
    ws = _workspace(client)
    action, _ = _running_capture(ws)
    assert _shot(action, b"<html>not an image</html>").status_code == 415
    # 框选要人拖,节点截不出来;页面图片也不是截图。
    assert _shot(action, _png(), capture="screenshot_region").status_code == 422
    assert _shot(action, _png(), capture="page_image").status_code == 422
    with SessionLocal() as db:
        assert db.query(Asset).filter_by(workspace_id=ws).count() == 0


def test_智能体也能截图() -> None:
    import asyncio

    import mcp_server

    tools = {tool.name for tool in asyncio.run(mcp_server.mcp.list_tools())}
    assert "browser_screenshot" in tools
