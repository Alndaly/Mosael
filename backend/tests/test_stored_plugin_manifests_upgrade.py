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
