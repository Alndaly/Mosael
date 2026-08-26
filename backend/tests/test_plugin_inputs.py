"""宿主把一份**文件**交给插件。

artifact 是插件交给宿主,这条是反过来。有了它插件才能做"上传"这类事。

**架构上这一条最要紧:`domain/plugins` 不认识素材库。** 插件声明的是「我要一个文件」,
至于文件从哪来是宿主的事 —— 和 jobs 不认识智能体是同一个手法。这里有一条用例直接钉住
那个依赖方向,因为它很容易在某次"顺手 import 一下"里没了。
"""

from __future__ import annotations

RATCHET = True

import json
import textwrap
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import Asset, PluginInstance, PluginPackage
from app.domain.plugins import inputs as plugin_inputs
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.tools import invoke
from tests.util import fresh_client

BACKEND = Path(__file__).resolve().parents[1]


class Test依赖方向:
    def test_插件系统不认识素材库(self) -> None:
        """一旦有人在 domain/plugins 里 import 了 assets,这条就红。

        它挡的不是洁癖:那个 import 一旦有了,「换一种来源」就得改插件这一层,而这条缝
        本来是为了让来源可换才存在的。
        """
        offenders = []
        for path in (BACKEND / "app" / "domain" / "plugins").rglob("*.py"):
            code = path.read_text(encoding="utf-8")
            body = "\n".join(line for line in code.splitlines() if not line.lstrip().startswith("#"))
            # 文档字符串里提一句不算 —— 判据是真的 import 语句。
            if "from app.domain.assets" in body or "import app.domain.assets" in body:
                offenders.append(path.name)
        assert offenders == [], f"这些文件 import 了素材库:{offenders}"

    def test_两个方向都走注入(self) -> None:
        from app.domain.plugins import media_bridge

        assert callable(media_bridge.sink()), "产出的落点没装配"
        assert callable(media_bridge.source()), "输入的来源没装配"


class Test声明:
    def test_按_format_认字段(self) -> None:
        """用 JSON Schema 的 `format` 而不是自造一个键:那个关键字的用途正是"这个字符串
        在语义上是什么",而且不认识它的工具会安静忽略,清单仍是合法的 JSON Schema。"""
        tool = {
            "input_schema": {
                "type": "object",
                "properties": {"a": {"type": "string", "format": "asset"}, "b": {"type": "string"}},
            }
        }
        assert plugin_inputs.asset_fields(tool) == ["a"]

    def test_没声明就不认(self) -> None:
        assert plugin_inputs.asset_fields({"input_schema": {"properties": {"x": {"type": "string"}}}}) == []

    def test_没有_schema_也不炸(self) -> None:
        assert plugin_inputs.asset_fields({}) == []


MANIFEST = {
    "id": "uploader",
    "name": "上传器",
    "version": "0.1.0",
    "runtime": {"kind": "process", "entry": "main.py"},
    "tools": {
        "expose": "all",
        "declare": [
            {
                "name": "send",
                "description": "把文件送走",
                "input_schema": {
                    "type": "object",
                    "properties": {"asset_id": {"type": "string", "format": "asset"}},
                    "required": ["asset_id"],
                },
            }
        ],
    },
}

ENTRY = """
    import json, os, sys
    request = json.loads(sys.stdin.read())
    path = request["input"]["asset_id"]
    print(json.dumps({"ok": True, "output": {
        "收到的": path,
        "是绝对路径": os.path.isabs(path),
        "文件在": os.path.isfile(path),
        "内容": open(path).read() if os.path.isfile(path) else "",
    }}))
"""


def _install(tmp_path: Path) -> tuple[str, str, str]:
    """装一个要文件的插件,并造一份素材。返回 (workspace, instance, asset)。"""
    plugin_dir = tmp_path / "p"
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text(textwrap.dedent(ENTRY), encoding="utf-8")

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    media = tmp_path / "成片.txt"
    media.write_text("这是一份素材", encoding="utf-8")

    with SessionLocal() as db:
        package = PluginPackage(id="uploader", name="上传器", version="0.1.0",
                                manifest={**MANIFEST, "_path": str(plugin_dir)})
        db.add(package)
        db.flush()
        instance = PluginInstance(package_id=package.id, name="上传器", enabled=True, owner_user_id="")
        db.add(instance)
        db.commit()
        from app.domain.assets import register_file_asset

        asset = register_file_asset(db, workspace_id=ws, project_id=None, source_path=media,
                                    name="成片.txt", source="imported")
        db.commit()
        return ws, instance.id, asset.id


class Test交给插件:
    def test_插件收到的是路径_不是_id(self, tmp_path) -> None:
        ws, instance_id, asset_id = _install(tmp_path)
        with SessionLocal() as db:
            invocation = invoke(db, instance_id, "send", {"asset_id": asset_id}, workspace_id=ws)
            assert invocation.status == "succeeded", invocation.error
            output = invocation.output
        assert output["文件在"] is True
        assert output["是绝对路径"] is True, "给了相对路径 —— 插件的 cwd 是它自己的目录"
        assert output["内容"] == "这是一份素材"
        assert asset_id not in output["收到的"], "把 id 原样传过去了"

    def test_给的是副本_不是库里那份(self, tmp_path) -> None:
        """给原件的话,插件改坏了或删掉了,用户丢的是库里那一份 —— 而插件是第三方代码。"""
        ws, instance_id, asset_id = _install(tmp_path)
        with SessionLocal() as db:
            output = invoke(db, instance_id, "send", {"asset_id": asset_id}, workspace_id=ws).output
            asset = db.get(Asset, asset_id)
            from app.media.paths import resolve_key

            assert Path(output["收到的"]) != resolve_key(asset.file_key)

    def test_用完就清(self, tmp_path) -> None:
        """暂存目录在 finally 里删。留着的话,上传几个大文件就能把磁盘写满。"""
        ws, instance_id, asset_id = _install(tmp_path)
        with SessionLocal() as db:
            output = invoke(db, instance_id, "send", {"asset_id": asset_id}, workspace_id=ws).output
        assert not Path(output["收到的"]).exists()

    def test_跨工作区不给(self, tmp_path) -> None:
        """插件的调用方可能是智能体,而它拿到的 id 可能来自任何地方 —— 这一条挡的是
        「用 A 工作区的连接把 B 工作区的素材传出去」。"""
        ws, instance_id, asset_id = _install(tmp_path)
        # 同一个库里的**另一个**工作区 —— 换 client 会重建库,插件也跟着没了。
        from app.db.models import Workspace

        with SessionLocal() as db:
            other = Workspace(name="别人的")
            db.add(other)
            db.commit()
            other_ws = other.id
            invocation = invoke(db, instance_id, "send", {"asset_id": asset_id}, workspace_id=other_ws)
        assert invocation.status == "failed"
        assert "工作区" in (invocation.error or "")

    def test_素材不存在时说得明白(self, tmp_path) -> None:
        ws, instance_id, _ = _install(tmp_path)
        with SessionLocal() as db:
            invocation = invoke(db, instance_id, "send", {"asset_id": "不存在"}, workspace_id=ws)
        assert invocation.status == "failed" and "不存在" in (invocation.error or "")

    def test_没有归属工作区时说清楚(self, tmp_path) -> None:
        ws, instance_id, asset_id = _install(tmp_path)
        with SessionLocal() as db:
            invocation = invoke(db, instance_id, "send", {"asset_id": asset_id}, workspace_id=None)
        assert invocation.status == "failed" and "工作区" in (invocation.error or "")


def test_这道棘轮扫得到东西() -> None:
    assert len(list((BACKEND / "app" / "domain" / "plugins").rglob("*.py"))) >= 8
