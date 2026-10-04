"""内嵌浏览器里**下载**的文件进素材库:不再弹系统保存框。

两个入口、同一套闸:

- 用户在会话窗口里点了下载:`POST /api/assets/web-download`(用户自己的会话,要有放东西的权限);
- 浏览器自动化点开了一个下载:执行器在跑那条动作时交上来,`POST /api/browser/worker/actions/{id}/artifact`
  (执行器密钥 + 那条动作的租约令牌),出处再记上是哪次运行、哪个节点触发的;
- 闸:大小上限(边收边数)、只收素材库认得的类型、文件名只取名字本身。
"""
from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core.db import SessionLocal
from app.db.models import Asset, BrowserAction
from app.domain import browser as bdom
from app.domain.assets import web_download
from app.domain.workflows.executors import browser as bx
from app.domain.workflows.run_scope import node_scope
from app.media.paths import resolve_key
from tests.util import fresh_client, second_client, worker_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (48, 30), (20, 120, 220)).save(buffer, format="PNG")
    return buffer.getvalue()


def _form(**fields) -> dict:
    return {
        "page_url": "https://example.com/gallery",
        "page_title": "图集",
        "source_url": "https://cdn.example.com/files/cover.png?sig=1",
        "captured_at": "2026-10-04T05:30:00.000Z",
        **fields,
    }


def _download(client, workspace_id: str, data: bytes, filename: str = "cover.png", **fields):
    return client.post(
        "/api/assets/web-download",
        data={"workspace_id": workspace_id, "filename": filename, **_form(**fields)},
        files={"file": ("blob", data, "application/octet-stream")},
    )


# ---------- 用户在会话窗口里点的下载 ----------


def test_手动下载的图片进素材库并记下出处() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _download(client, workspace_id, _png())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "image"
    assert body["source"] == "downloaded"
    assert body["name"] == "cover.png"
    info = body["media_info"]
    assert info["capture"] == "page_download"
    assert info["source_page_url"] == "https://example.com/gallery"
    assert info["source_page_title"] == "图集"
    # 下载的文件确实是从这个地址下下来的:记作它的来源地址。
    assert info["source_url"] == "https://cdn.example.com/files/cover.png?sig=1"
    # 不是自动化触发的:没有运行 / 节点。
    assert "source_run_id" not in info and "source_node_id" not in info


def test_手动下载的文档也收() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _download(client, workspace_id, b"# notes\nhello\n", filename="readme.md", source_url="")
    assert response.status_code == 200, response.text
    assert response.json()["kind"] == "document"


def test_素材库不认得的类型不收_一个字节都不落盘() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _download(client, workspace_id, b"PK\x03\x04 zip", filename="setup.zip")
    assert response.status_code == 415
    assert "setup.zip" in response.json()["detail"]
    with SessionLocal() as db:
        assert db.query(Asset).filter_by(workspace_id=workspace_id).count() == 0


def test_超过上限就停_不入库(monkeypatch) -> None:
    monkeypatch.setattr(web_download, "MAX_DOWNLOAD_BYTES", 1024)
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _download(client, workspace_id, b"\0" * 4096, filename="clip.mp4")
    assert response.status_code == 413
    with SessionLocal() as db:
        assert db.query(Asset).filter_by(workspace_id=workspace_id).count() == 0


def test_空文件不收() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _download(client, workspace_id, b"", filename="clip.mp4")
    assert response.status_code == 422


def test_文件名带路径_写不出素材目录() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _download(client, workspace_id, _png(), filename="../../../etc/x.png")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["name"] == "x.png"
    with SessionLocal() as db:
        asset = db.get(Asset, body["id"])
        path = resolve_key(asset.file_key)
    assert path.name == "x.png"
    assert path.parent.name == body["id"]


def test_safe_filename_清掉控制字符与分隔符() -> None:
    assert web_download.safe_filename("a\\b\\c:d?.pdf") == "c_d_.pdf"
    assert web_download.safe_filename("\x00\x1f.png") == "_.png"
    assert web_download.safe_filename("") == "download"
    long = "长" * 300 + ".mp4"
    assert web_download.safe_filename(long).endswith(".mp4") and len(web_download.safe_filename(long)) <= 121


def test_出处不像样就拒() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    assert _download(client, workspace_id, _png(), page_url="file:///etc/passwd").status_code == 422
    assert _download(client, workspace_id, _png(), source_url="blob:https://x/1").status_code == 422


def test_要登录_要有这个工作区的权限() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    client = fresh_client("owner")
    workspace_id = _workspace(client)
    assert _download(TestClient(app), workspace_id, _png()).status_code == 401
    assert _download(second_client("stranger"), workspace_id, _png()).status_code in (403, 404)


# ---------- 自动化里触发的下载:执行器交上来 ----------


def _running_action(workspace_id: str, *, origin: dict | None = None) -> tuple[dict, str]:
    """在会话里排一条动作并扮演执行器认领它,返回(认领到的动作, 会话 id)。"""
    with SessionLocal() as db:
        session_id = bdom.open_session(db, workspace_id=workspace_id, actor=None).id
        db.add(BrowserAction(
            session_id=session_id, workspace_id=workspace_id, action="click",
            args={"selector": "a.download", **({"origin": origin} if origin else {})}, status="queued",
        ))
        db.commit()
    action = worker_client().post("/api/browser/worker/claim", json={"worker": "test"}).json()["action"]
    assert action is not None
    return action, session_id


def _artifact(worker, action: dict, data: bytes, *, lease_token: str | None = None, **fields):
    form = {
        "lease_token": action["lease_token"] if lease_token is None else lease_token,
        "kind": "download",
        "filename": "report.pdf",
        **_form(source_url="https://example.com/files/report.pdf"),
        **fields,
    }
    return worker.post(
        f"/api/browser/worker/actions/{action['id']}/artifact", data=form,
        files={"file": ("blob", data, "application/octet-stream")},
    )


def test_自动化下载进素材库_记下是哪次运行哪个节点() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    action, session_id = _running_action(workspace_id, origin={"run": "job-123", "node": "n_click"})
    response = _artifact(worker_client(), action, _png(), filename="cover.png")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "image" and body["name"] == "cover.png"
    with SessionLocal() as db:
        asset = db.get(Asset, body["asset_id"])
        assert asset.workspace_id == workspace_id  # 进的是会话所在工作区
        info = asset.media_info
    assert info["capture"] == "page_download"
    assert info["source_url"] == "https://example.com/files/report.pdf"
    assert info["source_run_id"] == "job-123"
    assert info["source_node_id"] == "n_click"
    assert info["source_browser_session_id"] == session_id


def test_自动化下载_不是工作流发起的就只记会话() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    action, session_id = _running_action(workspace_id)
    response = _artifact(worker_client(), action, _png(), filename="cover.png")
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        info = db.get(Asset, response.json()["asset_id"]).media_info
    assert info["source_browser_session_id"] == session_id
    assert "source_run_id" not in info and "source_node_id" not in info


def test_自动化下载_令牌不对或动作已结束都不收() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    action, _ = _running_action(workspace_id)
    worker = worker_client()
    assert _artifact(worker, action, _png(), lease_token="someone-else", filename="a.png").status_code == 409
    worker.patch("/api/browser/worker/report", json={
        "action_id": action["id"], "status": "done", "result": {}, "lease_token": action["lease_token"],
    })
    late = _artifact(worker, action, _png(), filename="a.png")
    assert late.status_code == 409
    assert "来晚" in late.json()["detail"]
    with SessionLocal() as db:
        assert db.query(Asset).filter_by(workspace_id=workspace_id).count() == 0


def test_自动化下载_类型不收与超限都报人话(monkeypatch) -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    action, _ = _running_action(workspace_id)
    worker = worker_client()
    refused = _artifact(worker, action, b"MZ", filename="setup.exe")
    assert refused.status_code == 415 and "setup.exe" in refused.json()["detail"]
    monkeypatch.setattr(web_download, "MAX_DOWNLOAD_BYTES", 10)
    assert _artifact(worker, action, b"\0" * 100, filename="clip.mp4").status_code == 413


def test_自动化下载_要执行器密钥_产物种类有数() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    action, _ = _running_action(workspace_id)
    from fastapi.testclient import TestClient

    from app.main import app

    assert _artifact(TestClient(app), action, _png(), filename="a.png").status_code == 401
    # 用户的令牌也不行:这是执行器的通道。
    assert _artifact(client, action, _png(), filename="a.png").status_code == 401
    assert _artifact(worker_client(), action, _png(), filename="a.png", kind="cookies").status_code == 422


# ---------- 工作流节点:点下载 / 打开文件地址时交出素材 id ----------


def _wf(ws: str):
    import types

    return types.SimpleNamespace(workspace_id=ws, id="wf-test")


def test_点击节点把下载的素材id交出来_并带上是哪个节点(monkeypatch) -> None:
    seen: dict = {}

    def fake(sid, action, args, **kwargs):
        seen.update(action=action, args=args)
        return {"downloads": [{"asset_id": "asset-1", "name": "report.pdf", "bytes": 10}]}

    monkeypatch.setattr(bdom, "run_action", fake)
    client = fresh_client()
    ws = _workspace(client)
    with SessionLocal() as db:
        sid = bdom.open_session(db, workspace_id=ws, actor=None).id
        with node_scope("n_click"):
            out = bx.browser_click(db, _wf(ws), {"session": sid, "selector": "a.download"})
    assert out == {"session": sid, "asset_id": "asset-1"}
    assert seen["args"]["origin"] == {"run": "", "node": "n_click"}


def test_打开网址没下载时素材id是空串(monkeypatch) -> None:
    monkeypatch.setattr(bdom, "run_action", lambda sid, action, args, **k: {})
    client = fresh_client()
    ws = _workspace(client)
    with SessionLocal() as db:
        sid = bdom.open_session(db, workspace_id=ws, actor=None).id
        out = bx.browser_navigate(db, _wf(ws), {"session": sid, "url": "https://x.test"})
    assert out["asset_id"] == ""


@pytest.mark.parametrize("node", ["browser_navigate", "browser_click"])
def test_节点声明了下载素材这个输出(node) -> None:
    from app.domain.workflows import NODE_TYPES

    assert "asset_id" in NODE_TYPES[node]["outputs"]
