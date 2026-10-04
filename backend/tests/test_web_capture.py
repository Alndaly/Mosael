"""从内嵌浏览器存进素材库:截屏、页面上的图片(`POST /api/assets/capture`)。

钉住的是这条入口的四道闸和一份出处:

- **鉴权**:要登录、要有往这个工作区放东西的权限;
- **只收图片**:看文件头,不信客户端报的类型 —— 改个扩展名的 HTML 不进素材库;
- **大小上限**;
- **落盘目录与文件名由服务端定**:客户端给的文件名一律不用,`../../` 写不出素材目录;
- **出处**:来源网址、页面标题、截取时间、怎么截的,记在 media_info 里;页面图片另记图片自己的地址。
"""
from __future__ import annotations

import io

import pytest
from PIL import Image

from app.core.db import SessionLocal
from app.db.models import Asset
from app.domain.assets import web_capture
from app.media.paths import resolve_key
from tests.util import fresh_client, second_client


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _png(width: int = 64, height: int = 40) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(buffer, format="PNG")
    return buffer.getvalue()


def _capture(client, workspace_id: str, data: bytes, *, filename: str = "shot.png", **fields):
    form = {
        "workspace_id": workspace_id,
        "capture": "screenshot_visible",
        "page_url": "https://example.com/article?id=1",
        "page_title": "一篇文章",
        "captured_at": "2026-10-04T05:30:00.000Z",
        "name": "一篇文章 · 截图",
        **fields,
    }
    return client.post("/api/assets/capture", data=form, files={"file": (filename, data, "image/png")})


def test_截屏入库并记下出处() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _capture(client, workspace_id, _png(), capture="screenshot_full")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "image"
    assert body["source"] == "captured"
    assert body["name"] == "一篇文章 · 截图"
    info = body["media_info"]
    assert info["source_page_url"] == "https://example.com/article?id=1"
    assert info["source_page_title"] == "一篇文章"
    assert info["captured_at"] == "2026-10-04T05:30:00+00:00"
    assert info["capture"] == "screenshot_full"
    # 截图不是「从某个地址下载来的那份文件」:不冒充直链(见 providers 的 direct_media_url)。
    assert "source_url" not in info
    assert info["width"] == 64 and info["height"] == 40


def test_页面图片另记图片自己的地址() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _capture(
        client, workspace_id, _png(), capture="page_image", source_url="https://cdn.example.com/cover.png?w=640",
    )
    assert response.status_code == 200, response.text
    info = response.json()["media_info"]
    assert info["capture"] == "page_image"
    assert info["source_url"] == "https://cdn.example.com/cover.png?w=640"
    assert info["source_url_key"].startswith("url:https://cdn.example.com/cover.png")
    assert info["source_page_url"] == "https://example.com/article?id=1"


def test_文件名由服务端定_客户端给的路径写不出素材目录() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _capture(client, workspace_id, _png(), filename="../../../../evil.png")
    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        asset = db.get(Asset, response.json()["id"])
        assert asset is not None
        path = resolve_key(asset.file_key)
        assert path.is_file()
        assert "evil" not in path.name and ".." not in asset.file_key
        assert path.suffix == ".png"
        assert asset.id in asset.file_key


def test_不是图片不收_看文件头不看扩展名() -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _capture(client, workspace_id, b"<!doctype html><script>alert(1)</script>", filename="fake.png")
    assert response.status_code == 415
    with SessionLocal() as db:
        assert db.query(Asset).count() == 0


def test_超过大小上限不收(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(web_capture, "MAX_CAPTURE_BYTES", 100)
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _capture(client, workspace_id, _png(200, 200))
    assert response.status_code == 413
    with SessionLocal() as db:
        assert db.query(Asset).count() == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("capture", "screen_recording"),
        ("page_url", "file:///etc/passwd"),
        ("page_url", "javascript:alert(1)"),
        ("source_url", "ftp://example.com/a.png"),
        ("captured_at", "yesterday"),
    ],
)
def test_出处字段不合法就拒(field: str, value: str) -> None:
    client = fresh_client()
    workspace_id = _workspace(client)
    response = _capture(client, workspace_id, _png(), **{field: value})
    assert response.status_code == 422, response.text


def test_要登录() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    client = fresh_client()
    workspace_id = _workspace(client)
    response = _capture(TestClient(app), workspace_id, _png())
    assert response.status_code == 401


def test_别人的工作区放不进去() -> None:
    owner = fresh_client("owner")
    workspace_id = _workspace(owner)
    response = _capture(second_client("stranger"), workspace_id, _png())
    assert response.status_code in (403, 404)
    with SessionLocal() as db:
        assert db.query(Asset).count() == 0
