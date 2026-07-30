from __future__ import annotations

import pytest

from app.core.config import settings
from tests.util import fresh_client


@pytest.fixture
def sample_video(tmp_path):
    path = tmp_path / "dropped.mp4"
    path.write_bytes(b"fake-video-bytes")
    return path


def test_local_import_is_404_when_not_desktop(sample_video, monkeypatch) -> None:
    """团队服务器上这个接口必须不存在。

    它收的是一个由客户端指定的**本机绝对路径**;如果在服务器部署上也开着,任何客户端都能
    让服务器去读它自己的文件系统。门控是这个接口的安全边界,所以两个方向都得测——只测
    「开着能用」会让别人以为关掉也无所谓。
    """
    monkeypatch.setattr(settings, "local_desktop", False)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    res = client.post(
        "/api/assets/import-local",
        json={"workspace_id": ws["id"], "path": str(sample_video)},
    )
    assert res.status_code == 404


def test_local_import_ingests_file_on_desktop(sample_video, monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_desktop", True)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    res = client.post(
        "/api/assets/import-local",
        json={"workspace_id": ws["id"], "path": str(sample_video)},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["name"] == "dropped.mp4"
    assert body["source"] == "imported"
    # 真的落了盘:后续预览/导出都读这个 file_key。
    assert client.get(f"/api/assets/{body['id']}").status_code == 200


def test_local_import_rejects_unlisted_suffix(tmp_path, monkeypatch) -> None:
    """后缀白名单:这个接口不能退化成通用的任意文件读取器。"""
    monkeypatch.setattr(settings, "local_desktop", True)
    secret = tmp_path / "id_rsa"
    secret.write_bytes(b"-----BEGIN PRIVATE KEY-----")
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    res = client.post(
        "/api/assets/import-local",
        json={"workspace_id": ws["id"], "path": str(secret)},
    )
    assert res.status_code == 422


def test_local_import_rejects_missing_and_relative_paths(monkeypatch) -> None:
    monkeypatch.setattr(settings, "local_desktop", True)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    for bad in ("relative/path.mp4", "/definitely/not/here.mp4"):
        res = client.post("/api/assets/import-local", json={"workspace_id": ws["id"], "path": bad})
        assert res.status_code == 422, bad
