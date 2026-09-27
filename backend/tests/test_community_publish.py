"""发布到社区(ADR 0026 §4):工作流发的是「导出」那同一份文件、第二次发是新版本;插件包只装该装的。"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from app.core.config import settings
from app.core.db import SessionLocal
from app.db.models import Asset, PluginPackage, Workflow
from app.domain.community import CommunityError, publish
from tests.community_fake import connect, install
from tests.util import user_id

MANIFEST = {
    "id": "dev.test.community-demo",
    "name": "社区演示",
    "version": "1.0.0",
    "runtime": {"kind": "process", "entry": "main.py"},
    "permissions": ["network:demo"],
    "tools": {"expose": "all", "declare": [{"name": "go", "description": "跑一下"}]},
}


def _connected(monkeypatch):
    fake, client, clock = install(monkeypatch)
    connect(client, fake, clock)
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    return fake, client, ws


def test_工作流_发布再发布是新版本(monkeypatch) -> None:
    fake, client, ws = _connected(monkeypatch)
    workflow = client.post("/api/workflows", json={"workspace_id": ws, "name": "批量配音", "description": "说明"}).json()
    cover = settings.media_dir / "cover.png"
    cover.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    with SessionLocal() as db:
        db.add(Asset(id="cover-1", workspace_id=ws, kind="image", name="封面", file_key=str(cover.relative_to(settings.data_dir))))
        db.commit()

    first = client.post(
        f"/api/workflows/{workflow['id']}/community",
        json={"title": "批量配音", "summary": "一次配完", "tags": ["配音", "配音", " 批量 "], "cover_asset_id": "cover-1"},
    )
    assert first.status_code == 200, first.text
    result = first.json()
    assert result == {"slug": result["slug"], "url": f"https://community.test/workflows/{result['slug']}",
                      "version": "1", "status": "approved"}

    sent = fake.workflows[result["slug"]]["versions"][0]
    # 发的就是「导出」那一份文件。
    exported = client.get(f"/api/workflows/{workflow['id']}/export").json()
    assert sent["document"] == exported
    assert sent["fields"]["title"] == "批量配音" and sent["fields"]["summary"] == "一次配完"
    assert json.loads(sent["fields"]["tags"]) == ["配音", "批量"]
    assert sent["cover"][1] == cover.read_bytes()
    assert client.get(f"/api/workflows/{workflow['id']}").json()["community_slug"] == result["slug"]

    again = client.post(f"/api/workflows/{workflow['id']}/community", json={"title": "批量配音 v2"})
    assert again.status_code == 200, again.text
    assert again.json()["slug"] == result["slug"] and again.json()["version"] == "2"
    assert fake.count(f"/workflows/{result['slug']}/versions") == 1
    assert len(fake.workflows) == 1


def test_工作流_封面必须是这个工作区的图片(monkeypatch) -> None:
    _fake, client, ws = _connected(monkeypatch)
    workflow = client.post("/api/workflows", json={"workspace_id": ws, "name": "W", "description": ""}).json()
    refused = client.post(f"/api/workflows/{workflow['id']}/community", json={"cover_asset_id": "nope"})
    assert refused.status_code == 422
    assert "封面" in refused.json()["detail"]


def _plugin_dir(root: Path) -> Path:
    directory = root / MANIFEST["id"]
    (directory / "__pycache__").mkdir(parents=True)
    (directory / "lib").mkdir()
    (directory / "mosael.plugin.json").write_text(json.dumps(MANIFEST, ensure_ascii=False), encoding="utf-8")
    (directory / "main.py").write_text("print('{}')", encoding="utf-8")
    (directory / "lib" / "helper.py").write_text("X = 1", encoding="utf-8")
    (directory / "__pycache__" / "main.cpython-314.pyc").write_bytes(b"\0")
    (directory / "lib" / "helper.pyc").write_bytes(b"\0")
    (directory / ".DS_Store").write_bytes(b"\0")
    (directory / ".env").write_text("API_KEY=sk-author-secret", encoding="utf-8")
    (directory / "lib" / ".env.local").write_text("TOKEN=x", encoding="utf-8")
    (directory / "author.pem").write_text("-----BEGIN PRIVATE KEY-----", encoding="utf-8")
    return directory


def _names(data: bytes) -> list[str]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return sorted(archive.namelist())


def test_插件包_去掉缓存和密钥(tmp_path) -> None:
    data = publish.package_plugin(_plugin_dir(tmp_path))
    assert _names(data) == ["lib/helper.py", "main.py", "mosael.plugin.json"]
    assert b"sk-author-secret" not in data


@pytest.mark.skipif(shutil.which("git") is None, reason="需要 git")
def test_插件包_在_git_里只打受版本管理的文件(tmp_path) -> None:
    directory = _plugin_dir(tmp_path)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "add", f"{MANIFEST['id']}/mosael.plugin.json",
                    f"{MANIFEST['id']}/main.py", f"{MANIFEST['id']}/.env"], check=True)
    (directory / "scratch.txt").write_text("没提交的草稿", encoding="utf-8")
    # .env 就算被提交了也不进包;没提交的草稿和 lib/ 不进包。
    assert _names(publish.package_plugin(directory)) == ["main.py", "mosael.plugin.json"]


def test_插件_发布之后审核中(monkeypatch) -> None:
    fake, client, _ws = _connected(monkeypatch)
    _plugin_dir(settings.plugins_dir)
    assert client.post("/api/plugins/scan").status_code == 200
    published = client.post(f"/api/plugins/{MANIFEST['id']}/community", json={"summary": "演示", "tags": ["演示"]})
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "pending"
    sent = fake.plugins[-1]
    assert sent["filename"] == f"{MANIFEST['id']}.zip"
    assert _names(sent["zip"]) == ["lib/helper.py", "main.py", "mosael.plugin.json"]
    assert sent["fields"]["summary"] == "演示"
    shutil.rmtree(settings.plugins_dir / MANIFEST["id"])


def test_插件_清单坏了不往外发(monkeypatch, tmp_path) -> None:
    fake, client, _ws = _connected(monkeypatch)
    directory = tmp_path / "broken"
    directory.mkdir()
    (directory / "mosael.plugin.json").write_text(json.dumps({"name": "缺 id"}), encoding="utf-8")
    with SessionLocal() as db:
        package = PluginPackage(id="dev.test.broken", name="坏", version="0", manifest={"_path": str(directory)})
        db.add(package)
        db.commit()
        with pytest.raises(CommunityError, match="校验"):
            publish.publish_plugin(db, package=package, user_id=user_id(), summary="", tags=[])
    assert fake.plugins == []


def test_没连账号时发不了(monkeypatch) -> None:
    _fake, client, _clock = install(monkeypatch)
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    workflow = client.post("/api/workflows", json={"workspace_id": ws, "name": "W", "description": ""}).json()
    refused = client.post(f"/api/workflows/{workflow['id']}/community", json={})
    assert refused.status_code == 409
    with SessionLocal() as db:
        assert db.get(Workflow, workflow["id"]).community_slug == ""
