"""画板上跑插件工具,和工作流里的插件节点同一条规矩。

- 输出口叫 `artifact` / `artifacts` 的:收产出时换成了 `asset_id` / `asset_ids`,落板时按换过的名字取 ——
  此前按同名键取,那一口什么都落不下来;没声明类型时它们是素材,不是写着素材 id 的便签。
- 格子上存着的设置里,数组入参(非素材)存成了「名字 → 值」对象的,迁移成值的列表。

(`replaces` 改写之后的**下游输出引用**画板上没有:格子之间的绑定指向上游那一格(`{"from": 格子 id}`),
不指向产出者的某个输出口;落哪几格每一轮按新工具的声明现算。)
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from app.core.db import SessionLocal
from app.db.migrations import _migrate_board_plugin_array_inputs_are_lists
from app.db.models import Board, PluginInstance, PluginPackage
from app.domain.boards.tools import board_outputs
from app.domain.plugins.tools import refresh_tools
from tests.util import fresh_client, user_id

PACKAGE = "dev.test.boardlister"


MAKER = "dev.test.boardmaker"


def test_输出口叫artifact和artifacts的_落板落的是收进素材库的那几份_不是写着id的便签(tmp_path) -> None:
    """真插件交出文件、真执行器按口取值、真 node_meta,和画板跑一格(boards.tools._run_in_job)同一条组合。

    此前这条测试的输出是手工拼的(带着执行器根本不交的 asset_ids):两个口没声明类型时是 any,`artifacts` 那一串
    素材 id 被当文字落成便签,`artifact` 那一份也只在恰好出现在 asset_ids 里时才认得出。
    """
    from types import SimpleNamespace

    from app.domain.plugins.nodes import node_meta
    from app.domain.plugins.tools import find
    from app.domain.workflows.executors import get_executor
    from tests.util import acting_as

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    plugin_dir = tmp_path / "maker"
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text(textwrap.dedent("""
        import json, os, sys
        out = os.environ["MOSAEL_PLUGIN_OUTPUT_DIR"]
        for name in ("one.txt", "a.txt", "b.txt"):
            open(os.path.join(out, name), "w").write(name)
        print(json.dumps({"ok": True, "output": {
            "artifact": {"path": "one.txt"}, "artifacts": [{"path": "a.txt"}, {"path": "b.txt"}], "caption": "说明"}}))
    """), encoding="utf-8")
    tool = {"name": "make", "input_schema": {"type": "object", "properties": {}},
            "node": {"outputs": ["artifacts", "artifact", "caption"], "output_types": {"caption": "text"}}}
    manifest = {"id": MAKER, "name": "产出", "version": "0.1.0", "runtime": {"kind": "process", "entry": "main.py"},
                "tools": {"expose": "all", "declare": [tool]}, "_path": str(plugin_dir)}
    with SessionLocal() as db:
        db.add(PluginPackage(id=MAKER, name="产出", version="0.1.0", manifest=manifest))
        db.flush()
        instance = PluginInstance(package_id=MAKER, name="我的", enabled=True, owner_user_id=user_id())
        db.add(instance)
        db.commit()
        refresh_tools(db, instance, notify=False)
        db.commit()
        meta = node_meta(find(db, instance.id, "make"))
        with acting_as(db, user_id()):
            output = get_executor(f"plugin.{MAKER}.make")(db, SimpleNamespace(workspace_id=ws, id="b1", name="画板"), {})

    produced = board_outputs(meta, output)
    assets = [one for one in produced if one["type"] == "asset"]
    assert len(assets) == 3 and {one["asset_id"] for one in assets} == {output["artifact"], *output["artifacts"]}
    assert [one for one in produced if one["type"] != "asset"] == [{"type": "text", "text": "说明"}]


def _install(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "p"
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text(textwrap.dedent("""
        import json, sys
        print(json.dumps({"ok": True, "output": {}}))
    """), encoding="utf-8")
    manifest = {"id": PACKAGE, "name": "列表器", "version": "0.1.0", "runtime": {"kind": "process", "entry": "main.py"},
                "tools": {"expose": "all", "declare": [{"name": "join", "input_schema": {"type": "object", "properties": {
                    "items": {"type": "array", "items": {"type": "string"}}, "title": {"type": "string"}}}}]},
                "_path": str(plugin_dir)}
    with SessionLocal() as db:
        db.add(PluginPackage(id=PACKAGE, name="列表器", version="0.1.0", manifest=manifest))
        db.flush()
        instance = PluginInstance(package_id=PACKAGE, name="我的", enabled=True, owner_user_id=user_id())
        db.add(instance)
        db.commit()
        refresh_tools(db, instance, notify=False)
        db.commit()


def test_格子上存成映射的数组入参_迁移成值的列表(tmp_path) -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    _install(tmp_path)
    producer = f"node:plugin.{PACKAGE}.join"
    canvas = {"items": [
        {"id": "slot", "kind": "text", "form": {"producer": producer, "config": {"items": {"a": "一", "b": "二"}, "title": "t"}}},
        {"id": "cell", "kind": "image", "form": {"abilities": {producer: {"config": {"items": {"x": "甲"}}, "bindings": {}}}}},
        {"id": "plain", "kind": "text", "text": "不动"},
    ], "edges": []}
    with SessionLocal() as db:
        board = Board(workspace_id=ws, name="老画板", canvas=canvas, revision=3)
        db.add(board)
        db.commit()
        board_id = board.id

    _migrate_board_plugin_array_inputs_are_lists()
    _migrate_board_plugin_array_inputs_are_lists()  # 再跑什么都不改

    with SessionLocal() as db:
        board = db.get(Board, board_id)
        items = {item["id"]: item for item in board.canvas["items"]}
        assert board.revision == 4
    assert items["slot"]["form"]["config"] == {"items": ["一", "二"], "title": "t"}
    assert items["cell"]["form"]["abilities"][producer]["config"] == {"items": ["甲"]}
    assert items["plain"] == canvas["items"][2]
