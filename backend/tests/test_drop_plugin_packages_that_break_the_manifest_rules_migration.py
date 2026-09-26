"""`drop-plugin-packages-that-break-the-manifest-rules`:清单形状收紧之后,库里违反新规矩的包记录删掉。

不删的话,`manifest_of` 读到它就抛 —— 插件页、智能体工具表对**所有人**报错,而这样的包本来也跑不了。
合规矩的包(包括仓库里的每一个第一方插件)一个不动;再跑一次什么都不变。
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.migrations import _drop_plugin_packages_that_break_the_manifest_rules as migrate
from app.db.models import PluginCredential, PluginInstance, PluginPackage
from app.domain.plugins.manifest import manifest_of
from tests.util import fresh_client

BASE = {"name": "x", "version": "1.0.0", "runtime": {"kind": "process", "entry": "main.py"}}

BROKEN = {
    "../escaped": {**BASE, "id": "../escaped"},
    "dev.dotted-tool": {**BASE, "id": "dev.dotted-tool", "tools": {"declare": [{"name": "v1.upload"}]}},
    "dev.twice": {**BASE, "id": "dev.twice", "tools": {"declare": [{"name": "go"}, {"name": "go"}]}},
    "dev.path-key": {**BASE, "id": "dev.path-key", "instance": {"config": [{"key": "path", "label": "路径"}]}},
    "dev.host-key": {**BASE, "id": "dev.host-key", "instance": {"credentials": [{"key": "MOSAEL_LOCALE", "label": "x"}]}},
    "dev.collide": {**BASE, "id": "dev.collide", "instance": {
        "config": [{"key": "token", "label": "a"}], "credentials": [{"key": "TOKEN", "label": "b"}]}},
}

FINE = {
    "dev.fine": {**BASE, "id": "dev.fine", "tools": {"declare": [{"name": "go"}]},
                 "instance": {"credentials": [{"key": "API_KEY", "label": "k"}], "config": [{"key": "bad key", "label": "丢掉的"}]}},
}


def test_违反新规矩的包记录删掉_连接和凭据随之走_合规矩的一个不动() -> None:
    fresh_client()
    first_party = Path(__file__).resolve().parents[2] / "plugins"
    shipped = {
        raw["id"]: raw
        for raw in (json.loads(path.read_text(encoding="utf-8")) for path in first_party.glob("*/*/mosael.plugin.json"))
    }
    with SessionLocal() as db:
        existing = set(db.scalars(select(PluginPackage.id)))
        for package_id, raw in {**BROKEN, **FINE, **{k: v for k, v in shipped.items() if k not in existing}}.items():
            db.add(PluginPackage(id=package_id, name="x", version="1", manifest=raw))
        db.flush()
        doomed = PluginInstance(package_id="dev.path-key", name="要走的")
        kept = PluginInstance(package_id="dev.fine", name="留下的")
        db.add_all([doomed, kept])
        db.flush()
        db.add_all([
            PluginCredential(instance_id=doomed.id, key="x", value="秘密"),
            PluginCredential(instance_id=kept.id, key="API_KEY", value="留着"),
        ])
        db.commit()
        doomed_id, kept_id = doomed.id, kept.id

    migrate()

    with SessionLocal() as db:
        remaining = set(db.scalars(select(PluginPackage.id)))
        assert not remaining & set(BROKEN), "违反新规矩的包还在"
        assert {"dev.fine", *shipped} <= remaining, "合规矩的包被误删了"
        assert db.get(PluginInstance, doomed_id) is None
        assert db.get(PluginCredential, {"instance_id": doomed_id, "key": "x"}) is None
        assert db.get(PluginInstance, kept_id) is not None
        # 留下的每一个都读得出来 —— 这正是这条迁移要保证的。
        for package in db.scalars(select(PluginPackage)):
            manifest_of(package)

    migrate()  # 幂等
    with SessionLocal() as db:
        assert set(db.scalars(select(PluginPackage.id))) == remaining
