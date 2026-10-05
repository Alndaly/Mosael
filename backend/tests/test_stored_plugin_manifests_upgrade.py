"""`upgrade-stored-plugin-manifests`:包记录里存着的清单跟着清单迁移链升到当前版本。

装着 Manim 0.2 的库:它的清单带一个 `PIP_INDEX_URL` 配置项,而镜像改由宿主注入之后那是宿主占着的名字 ——
记录里那份解析不过,插件页、智能体会话一碰到插件就 500(用户撞到的:插件列表「暂时无法加载」)。磁盘上的清单
只在扫描时升,扫描要人点;所以启动时对一遍记录。配置项变成 `package_sources` 的声明,`_path` 留着。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import text

from app.core.db import SessionLocal, engine
from app.db.migrations import _upgrade_stored_plugin_manifests as reconcile
from app.db.models import PluginPackage
from app.domain.plugins.manifest import PATH_KEY, ManifestError, manifest_of
from app.domain.plugins.migrations import MANIFEST_VERSION, migrate_directory
from tests.util import fresh_client

#: Manim 0.2.0 装进插件目录后的清单(节选到出事的那部分)。
MANIM_0_2 = {
    "id": "dev.mosael.manim",
    "manifest_version": 1,
    "name": "Manim",
    "version": "0.2.0",
    "runtime": {"kind": "process", "entry": ["python3", "tools/main.py"]},
    "instance": {
        "config": [
            {"key": "PIP_INDEX_URL", "label": "pip 镜像", "type": "string"},
            {"key": "UNRESTRICTED_CODE", "label": "不限制自定义代码", "type": "boolean", "default": "false"},
        ]
    },
    "tools": {"expose": "all", "declare": [{"name": "render", "description": "渲染"}]},
}


def test_存着老清单的包_启动对一遍之后插件页打得开_镜像配置项成了声明() -> None:
    client = fresh_client()
    with SessionLocal() as db:
        db.add(PluginPackage(id="dev.mosael.manim", name="Manim", version="0.2.0",
                             manifest={**MANIM_0_2, PATH_KEY: "/plugins/dev.mosael.manim"}))
        db.commit()
    with SessionLocal() as db, pytest.raises(ManifestError):
        manifest_of(db.get(PluginPackage, "dev.mosael.manim"))

    reconcile()
    reconcile()

    with SessionLocal() as db:
        package = db.get(PluginPackage, "dev.mosael.manim")
        manifest = manifest_of(package)
        assert package.manifest[PATH_KEY] == "/plugins/dev.mosael.manim"
        assert package.manifest["manifest_version"] == MANIFEST_VERSION
    assert manifest.package_sources == ["pypi"]
    assert [field.key for field in manifest.config] == ["UNRESTRICTED_CODE"]
    response = client.get("/api/plugins")
    assert response.status_code == 200, response.text
    assert "dev.mosael.manim" in {one["id"] for one in response.json()}


#: Remotion 0.2.0 的清单:镜像是插件自己起名的 `NPM_REGISTRY`,不是宿主占着的名字,所以解析得过 ——
#: 但连接里填的值已经搬成连接自己的下载源,这一格留着就是同一个设置的第二处,还显示成空的。
REMOTION_0_2 = {
    "id": "dev.mosael.remotion",
    "manifest_version": 2,
    "name": "Remotion",
    "version": "0.2.0",
    "runtime": {"kind": "process", "entry": ["python3", "tools/main.py"]},
    "instance": {"config": [
        {"key": "NPM_REGISTRY", "label": "npm 镜像", "type": "string"},
        {"key": "BROWSER_EXECUTABLE", "label": "浏览器路径", "type": "string"},
    ]},
}


def test_Remotion老版的npm镜像框换成下载源_别的包里同名的键不碰() -> None:
    fresh_client()
    other = {**REMOTION_0_2, "id": "dev.example.other", "name": "Other"}
    with SessionLocal() as db:
        db.add(PluginPackage(id="dev.mosael.remotion", name="Remotion", version="0.2.0",
                             manifest={**REMOTION_0_2, PATH_KEY: "/plugins/dev.mosael.remotion"}))
        db.add(PluginPackage(id="dev.example.other", name="Other", version="0.2.0", manifest={**other, PATH_KEY: "/o"}))
        db.commit()

    reconcile()

    with SessionLocal() as db:
        remotion = manifest_of(db.get(PluginPackage, "dev.mosael.remotion"))
        untouched = manifest_of(db.get(PluginPackage, "dev.example.other"))
    assert remotion.package_sources == ["npm"]
    assert [field.key for field in remotion.config] == ["BROWSER_EXECUTABLE"]
    assert untouched.package_sources == []
    assert [field.key for field in untouched.config] == ["NPM_REGISTRY", "BROWSER_EXECUTABLE"]


def test_当前版本的记录不动() -> None:
    fresh_client()
    current = {**MANIM_0_2, "manifest_version": MANIFEST_VERSION, "instance": {}, PATH_KEY: "/x"}
    with SessionLocal() as db:
        db.add(PluginPackage(id="dev.mosael.manim", name="Manim", version="0.3.1", manifest=current))
        db.commit()
    with engine.begin() as conn:
        before = conn.execute(text("SELECT manifest FROM plugin_packages WHERE id = 'dev.mosael.manim'")).scalar_one()
    reconcile()
    with engine.begin() as conn:
        assert conn.execute(text("SELECT manifest FROM plugin_packages WHERE id = 'dev.mosael.manim'")).scalar_one() == before


def test_磁盘上的老清单扫描时走同一串步骤(tmp_path: Path) -> None:
    (tmp_path / "mosael.plugin.json").write_text(json.dumps(MANIM_0_2), encoding="utf-8")
    path = migrate_directory(tmp_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["package_sources"] == ["pypi"]
    assert [one["key"] for one in raw["instance"]["config"]] == ["UNRESTRICTED_CODE"]
    assert raw["manifest_version"] == MANIFEST_VERSION


def test_认领调用类能力的工具_素材入参补成契约的形状() -> None:
    """ADR 0033:这些工具此前只经宿主调,宿主把副本路径直接塞进 `file`,入参上用不着标记;现在它们是普通工具,
    智能体、工作流按 `format: asset` 才知道那一格交一份素材。已装的老清单在启动时补上,不然解析不过。"""
    fresh_client()
    old = {
        "id": "dev.example.asr", "manifest_version": 3, "name": "ASR", "version": "0.1.0",
        "provides": ["transcription"], "runtime": {"kind": "process", "entry": ["python3", "main.py"]},
        "tools": {"declare": [{"name": "hear", "provides": ["transcription"], "input_schema": {
            "type": "object", "properties": {"file": {"type": "string", "x-media": "audio"}, "language": {"type": "string"}}}}]},
    }
    with SessionLocal() as db:
        db.add(PluginPackage(id="dev.example.asr", name="ASR", version="0.1.0", manifest={**old, PATH_KEY: "/a"}))
        db.commit()
    with SessionLocal() as db, pytest.raises(ManifestError):
        manifest_of(db.get(PluginPackage, "dev.example.asr"))

    reconcile()

    with SessionLocal() as db:
        manifest = manifest_of(db.get(PluginPackage, "dev.example.asr"))
    file = manifest.declared_tools[0]["input_schema"]["properties"]["file"]
    assert file == {"type": "string", "format": "asset", "x-media": ["audio", "video"], "x-audio": "speech"}


#: 清单版本 6 的写法:`skills` 是给别的智能体看的工具目录。版本 7 改叫 `toolsets`(ADR 0040 §8)。
V6_WITH_SKILLS = {
    "id": "dev.example.tikhub", "manifest_version": 6, "name": "TikHub", "version": "0.4.0",
    "runtime": {"kind": "mcp", "url": "https://mcp.example.com"},
    "skills": [{"id": "tikhub", "description": {"zh": "抓取各平台的公开数据", "en": "Fetch public data"}}],
}


def test_v6的skills在库里和磁盘上都改名成toolsets_介绍照旧取第一条(tmp_path: Path) -> None:
    fresh_client()
    with SessionLocal() as db:
        db.add(PluginPackage(id="dev.example.tikhub", name="TikHub", version="0.4.0",
                             manifest={**V6_WITH_SKILLS, PATH_KEY: "/t"}))
        db.commit()

    reconcile()

    with SessionLocal() as db:
        package = db.get(PluginPackage, "dev.example.tikhub")
        stored, manifest = dict(package.manifest), manifest_of(package)
    assert "skills" not in stored and stored["toolsets"] == V6_WITH_SKILLS["skills"]
    assert stored["manifest_version"] == MANIFEST_VERSION == 7
    assert [one["id"] for one in manifest.toolsets] == ["tikhub"]
    assert manifest.description == "抓取各平台的公开数据"

    (tmp_path / "mosael.plugin.json").write_text(json.dumps(V6_WITH_SKILLS), encoding="utf-8")
    on_disk = json.loads(migrate_directory(tmp_path).read_text(encoding="utf-8"))
    assert "skills" not in on_disk and on_disk["toolsets"] == V6_WITH_SKILLS["skills"]
    assert (tmp_path / "mosael.plugin.json.bak").exists(), "改用户磁盘上的文件之前留一份"


def test_旧路由名不再存在_新名字答得上() -> None:
    client = fresh_client()
    assert client.get("/api/agent/skills").status_code == 404
    body = client.get("/api/agent/toolsets").json()
    assert "mosael.assets" in {one["id"] for one in body}
    assert "toolsets" in client.get("/api/agent/manifest").json()
