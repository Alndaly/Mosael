"""可以不填的数组(`"type": ["array", "null"]`)和普通数组是同一种东西:表单、运行时、素材换路径、迁移读同一条
`plugins.inputs.schema_type`。

此前只有表单认联合类型(给了一行一项的编辑器 / 素材选择器),运行时、换路径、迁移只认 `type == "array"`:
一行一整串引用没拼开、数字文字没转;素材数组把素材 id 原样交给插件;存成「名字 → 值」的老值没迁到。

装一个真的进程插件、走 invoke / 迁移函数本体,不把 coerce / materialize 换掉。
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from sqlalchemy import text

from app.core.db import SessionLocal
from app.db.migrations import _migrate_plugin_union_array_inputs_are_lists
from app.db.models import Board, PluginInstance, PluginPackage, Workflow
from app.domain.plugins.nodes import node_meta
from app.domain.plugins.tools import invoke, refresh_tools
from app.domain.workflows import create_workflow
from app.domain.workflows.revisions import graph_digest
from tests.util import fresh_client, user_id

PACKAGE = "dev.test.unioner"
ENTRY = """
    import json, os, sys
    request = json.loads(sys.stdin.read())
    given = request["input"]
    if request["tool"] == "join":
        print(json.dumps({"ok": True, "output": {"parts": given.get("parts"), "sizes": given.get("sizes")}}))
    else:
        files = given.get("files") or []
        print(json.dumps({"ok": True, "output": {
            "files": [os.path.isabs(one) and os.path.isfile(one) for one in files],
            "texts": [open(one).read() for one in files if os.path.isfile(one)],
        }}))
"""
TOOLS = [
    {"name": "join", "input_schema": {"type": "object", "properties": {
        "parts": {"type": ["array", "null"], "items": {"type": "string"}},
        "sizes": {"type": ["array", "null"], "items": {"type": ["integer", "null"]}},
    }}},
    {"name": "send", "input_schema": {"type": "object", "properties": {
        "files": {"type": ["array", "null"], "items": {"type": "string", "format": "asset"}},
    }}},
]


def _install(tmp_path: Path) -> tuple[str, str]:
    plugin_dir = tmp_path / "unioner"
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / "main.py").write_text(textwrap.dedent(ENTRY), encoding="utf-8")
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    manifest = {"id": PACKAGE, "name": "联合", "version": "0.1.0", "runtime": {"kind": "process", "entry": "main.py"},
                "tools": {"expose": "all", "declare": TOOLS}, "_path": str(plugin_dir)}
    with SessionLocal() as db:
        db.add(PluginPackage(id=PACKAGE, name="联合", version="0.1.0", manifest=manifest))
        db.flush()
        instance = PluginInstance(package_id=PACKAGE, name="我的", enabled=True, owner_user_id=user_id())
        db.add(instance)
        db.commit()
        refresh_tools(db, instance, notify=False)
        db.commit()
        return ws, instance.id


def test_可以不填的数组_表单和运行时一样当数组(tmp_path) -> None:
    ws, instance_id = _install(tmp_path)
    assert node_meta(TOOLS[0])["config"]["parts"]["type"] == "list"
    with SessionLocal() as db:
        invocation = invoke(db, instance_id, "join", {"parts": ["一", ["二", "三"], ""], "sizes": ["1", "2"]},
                            workspace_id=ws)
    assert invocation.status == "succeeded", invocation.error
    assert (invocation.output["parts"], invocation.output["sizes"]) == (["一", "二", "三"], [1, 2])


def test_可以不填的素材数组_插件收到的是路径(tmp_path) -> None:
    from app.domain.assets import register_file_asset

    ws, instance_id = _install(tmp_path)
    config = node_meta(TOOLS[1])["config"]["files"]
    assert config["type"] == "asset_list" and config["data_type"] == "asset"
    media = tmp_path / "稿子.txt"
    media.write_text("一份素材", encoding="utf-8")
    with SessionLocal() as db:
        asset = register_file_asset(db, workspace_id=ws, project_id=None, source_path=media, name="稿子.txt",
                                    source="imported")
        db.commit()
        invocation = invoke(db, instance_id, "send", {"files": [asset.id]}, workspace_id=ws)
    assert invocation.status == "succeeded", invocation.error
    assert (invocation.output["files"], invocation.output["texts"]) == ([True], ["一份素材"]), "素材 id 原样交给了插件"


_START_ONLY = {"nodes": [{"id": "start", "type": "start", "config": {}}], "edges": []}


def test_存成映射的可以不填的数组_工作流和画板上都迁成值的列表(tmp_path) -> None:
    ws, _ = _install(tmp_path)
    kind = f"plugin.{PACKAGE}.join"
    graph = {"nodes": [
        {"id": "start", "type": "start", "config": {}},
        {"id": "j", "type": kind, "config": {"parts": {"a": "一", "b": "{{start.x}}"}}},
        {"id": "loop", "type": "loop_foreach", "config": {"items": "[1]", "body": {
            "nodes": [{"id": "k", "type": kind, "config": {"parts": {"a": "甲"}, "sizes": ["1"]}}], "edges": []}}},
    ], "edges": [{"id": "e1", "source": "start", "target": "j"}]}
    canvas = {"items": [
        {"id": "slot", "kind": "text", "form": {"producer": f"node:{kind}", "config": {"parts": {"a": "一"}}}},
        {"id": "cell", "kind": "image", "form": {"abilities": {f"node:{kind}": {"config": {"parts": {"x": "乙"}}}}}},
        {"id": "plain", "kind": "text", "text": "不动"},
    ], "edges": []}
    with SessionLocal() as db:
        workflow_id = create_workflow(db, workspace_id=ws, name="老流程", graph=_START_ONLY, created_by=user_id()).id
        board = Board(workspace_id=ws, name="老画板", canvas=canvas, revision=3)
        db.add(board)
        db.commit()
        board_id = board.id
        #: 老版本存下的样子(现在的保存会按声明把映射规范化成列表):当前图和修订都是映射。
        for table, column in (("workflows", "id"), ("workflow_revisions", "workflow_id")):
            db.execute(text(f"UPDATE {table} SET graph = :g, graph_hash = :h WHERE {column} = :id"),
                       {"g": json.dumps(graph, ensure_ascii=False), "h": graph_digest(graph), "id": workflow_id})
        db.commit()

    _migrate_plugin_union_array_inputs_are_lists()
    _migrate_plugin_union_array_inputs_are_lists()  # 再跑什么都不改

    with SessionLocal() as db:
        workflow = db.get(Workflow, workflow_id)
        assert workflow.revision == 2
        nodes = {node["id"]: node for node in workflow.graph["nodes"]}
        board = db.get(Board, board_id)
        assert board.revision == 4
        items = {item["id"]: item for item in board.canvas["items"]}
    assert nodes["j"]["config"] == {"parts": ["一", "{{start.x}}"]}
    assert nodes["loop"]["config"]["body"]["nodes"][0]["config"] == {"parts": ["甲"], "sizes": ["1"]}
    assert items["slot"]["form"]["config"] == {"parts": ["一"]}
    assert items["cell"]["form"]["abilities"][f"node:{kind}"]["config"] == {"parts": ["乙"]}
    assert items["plain"] == canvas["items"][2]
