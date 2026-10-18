"""从图片直链导入素材(`POST /api/assets/import-image-url`)。

内嵌浏览器采集那条路收的是客户端交来的字节;这条收的是**一个地址** —— 所以它要重走
一遍截图那条路的闸,而不是新写一套:

- 只收图片(看文件头,不信后缀、也不全信 Content-Type);
- 40 MiB 上限(与截图同一个常量);
- 出站检查(别人给的地址,桌面版也默认只许公网);
- 落盘/探测/缩略图交给 `importer.import_binary_asset`,出处记成 `source_url`。

测试里不连外网:HTTP 客户端打桩,返回本地造出来的字节。
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image

from app.core.db import SessionLocal
from app.db.models import Asset
from app.domain.assets import web_capture
from app.domain.assets import from_url
from tests.util import fresh_client


def _png(width: int = 48, height: int = 32) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (20, 120, 220)).save(buffer, format="PNG")
    return buffer.getvalue()


class _FakeResponse:
    def __init__(self, chunks: list[bytes], content_type: str = "image/png", status_code: int = 200) -> None:
        self._chunks = chunks
        self.headers = {"content-type": content_type}
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import httpx

            request = httpx.Request("GET", "https://cdn.example.com/image.png")
            raise httpx.HTTPStatusError("bad status", request=request, response=httpx.Response(self.status_code, request=request))

    def iter_bytes(self):
        return iter(self._chunks)

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


class _FakeClient:
    def __init__(self, response: _FakeResponse) -> None:
        self.response = response

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def stream(self, method: str, url: str, **kwargs):
        return self.response


def _serve(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse, *, public: bool = True) -> None:
    monkeypatch.setattr(from_url, "RetryingClient", lambda **kwargs: _FakeClient(response))
    if public:
        monkeypatch.setattr(from_url, "ensure_public_link", lambda url: None)


def _workspace(client) -> str:
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _import_image(client, workspace_id: str, url: str, **body):
    return client.post(
        "/api/assets/import-image-url",
        json={"workspace_id": workspace_id, "url": url, **body},
    )


def test_贴一张图_落成_image_并记下出处(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, _FakeResponse([_png()]))
    client = fresh_client()
    workspace_id = _workspace(client)

    response = _import_image(client, workspace_id, "https://cdn.example.com/cover.png?w=640")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "image"
    assert body["source"] == "downloaded"
    info = body["media_info"]
    # 它确实是「从某个地址下载来的那份文件」:记作来源地址,和直链导入的视频同一套。
    assert info["source_url"] == "https://cdn.example.com/cover.png?w=640"
    assert info["source_url_key"].startswith("url:https://cdn.example.com/cover.png")
    # 真的落了盘:后续预览、导出都读这个 file_key。
    assert client.get(f"/api/assets/{body['id']}").status_code == 200


def test_看文件头_不改扩展名的_HTML_不收(monkeypatch: pytest.MonkeyPatch) -> None:
    """Content-Type 说是图片也不行 —— 字节是一张网页就拒,和截图那条同一个判据。"""
    _serve(monkeypatch, _FakeResponse([b"<!doctype html><script>alert(1)</script>"], content_type="image/png"))
    client = fresh_client()
    workspace_id = _workspace(client)

    response = _import_image(client, workspace_id, "https://cdn.example.com/fake.png")

    assert response.status_code == 415, response.text
    with SessionLocal() as db:
        assert db.query(Asset).count() == 0


def test_超过截图那条_40MiB_上限就拒(monkeypatch: pytest.MonkeyPatch) -> None:
    """上限和截图同一个常量,不是另定一个数。为了测边界,这里只把它调小。"""
    assert web_capture.MAX_CAPTURE_BYTES == 40 * 1024 * 1024
    monkeypatch.setattr(web_capture, "MAX_CAPTURE_BYTES", 64)
    _serve(monkeypatch, _FakeResponse([_png(128, 128)]))
    client = fresh_client()
    workspace_id = _workspace(client)

    response = _import_image(client, workspace_id, "https://cdn.example.com/big.png")

    assert response.status_code == 413, response.text
    assert "太大" in response.text or "too large" in response.text.lower()
    with SessionLocal() as db:
        assert db.query(Asset).count() == 0


def test_上限交给_save_capped_的仍是_40MiB(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, int | None] = {}
    real = from_url.web_download.save_capped

    def spy(stream, target: Path, limit: int | None = None) -> int:
        seen["limit"] = limit
        return real(stream, target, limit=limit)

    monkeypatch.setattr(from_url.web_download, "save_capped", spy)
    _serve(monkeypatch, _FakeResponse([_png()]))
    client = fresh_client()
    workspace_id = _workspace(client)

    assert _import_image(client, workspace_id, "https://cdn.example.com/cover.png").status_code == 200
    assert seen["limit"] == web_capture.MAX_CAPTURE_BYTES


def test_私网图片地址被出站守卫拦下() -> None:
    """别人给的地址:桌面版也默认只许公网。这条不连网 —— 守卫在连接之前就拒。"""
    client = fresh_client()
    workspace_id = _workspace(client)

    response = _import_image(client, workspace_id, "http://127.0.0.1:9/secret.png")

    assert response.status_code == 422, response.text
    assert "127.0.0.1" in response.text or "内网" in response.text or "private" in response.text.lower()


def test_不是_http_地址的图片不会落到库里(monkeypatch: pytest.MonkeyPatch) -> None:
    """权限/链接格式不对时,一个字节都不该落盘:守卫在下载之前。"""
    _serve(monkeypatch, _FakeResponse([_png()]), public=False)
    client = fresh_client()
    workspace_id = _workspace(client)

    response = _import_image(client, workspace_id, "not-a-url")
    assert response.status_code in (422, 415), response.text
    with SessionLocal() as db:
        assert db.query(Asset).count() == 0


def test_取不到地址时说的不是网络成功(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx

    def fail(**kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(from_url, "RetryingClient", fail)
    monkeypatch.setattr(from_url, "ensure_public_link", lambda url: None)
    client = fresh_client()
    workspace_id = _workspace(client)

    response = _import_image(client, workspace_id, "https://cdn.example.com/cover.png")
    assert response.status_code == 422, response.text
    assert "urlImportErr_network" not in response.text
    assert "网络" in response.text or "reach" in response.text.lower()
