"""画板上**不按另一个系统里的编号去取东西**(ADR 0021 修订 3,boards.transforms 的 `external_id`)。

用户看到「添加」菜单里有「导入 ComfyUI 产出」:它的入参是 ComfyUI 的任务号 —— 按一个外部编号去取东西,不是内容变换。
它能进来,是因为规矩 3 放过「不吃内容、交出素材」的工具(本意是提示词出图)。网盘的「导入」(fs_id)、对象存储的
「取回」(对象路径)是同一类。字段在声明里说清「这是另一个系统里的编号」(`format: "external_id"`),规矩按它判:
必填一个编号,或者不吃画板内容却收一个编号的,不上画板;工作流和智能体照旧用得上。

存着的这种工具格由对账改成一张便签(和内置流程节点改成便签的那次迁移一个做法);对账没改到的,跑的时候说清楚。
"""

from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

from tests.test_board_producers import _action_board, _me, _run_tool, _workspace
from tests.util import fresh_client

PACKAGE = "dev.test.fetchers"
PRODUCER = f"node:plugin.{PACKAGE}.fetch"

#: `fetch` 按网盘的 fs_id 取回一个文件(必填编号);`recent` 按任务号取回、不给就取最近几次(选填编号);
#: `paint` 按提示词出图 —— 凭空产出,照旧上画板。
TOOLS = [
    {"name": "fetch", "label": {"zh": "从网盘导入", "en": "Import from the drive"},
     "input_schema": {"type": "object", "properties": {"fs_id": {"type": "string", "format": "external_id"}},
                      "required": ["fs_id"]},
     "node": {"outputs": ["asset_id"], "output_types": {"asset_id": "asset"}}},
    {"name": "recent", "input_schema": {"type": "object", "properties": {
        "prompt_id": {"type": "string", "format": "external_id"}, "last": {"type": "integer"}}},
     "node": {"outputs": ["asset_id"], "output_types": {"asset_id": "asset"}}},
    {"name": "paint", "input_schema": {"type": "object", "properties": {"prompt": {"type": "string"}}},
     "node": {"outputs": ["asset_id"], "output_types": {"asset_id": "asset"}}},
]

ENTRY = """
import json, sys
print(json.dumps({"ok": True, "output": {}}))
"""


def _install(root: Path) -> None:
    from app.core.db import SessionLocal
    from app.db.models import PluginPackage

    plugin_dir = root / PACKAGE
    shutil.rmtree(plugin_dir, ignore_errors=True)
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "main.py").write_text(textwrap.dedent(ENTRY), encoding="utf-8")
    manifest = {"id": PACKAGE, "name": "取东西", "version": "0.1.0", "runtime": {"kind": "process", "entry": "main.py"},
                "tools": {"expose": "all", "declare": TOOLS}, "_path": str(plugin_dir)}
    (plugin_dir / "mosael.plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    with SessionLocal() as db:
        db.add(PluginPackage(id=PACKAGE, name="取东西", version="0.1.0", manifest=manifest))
        db.commit()


def _connect(owner_id: str) -> str:
    from app.core.db import SessionLocal
    from app.db.models import PluginInstance
    from app.domain.plugins.tools import refresh_tools

    with SessionLocal() as db:
        instance = PluginInstance(package_id=PACKAGE, name="我的网盘", enabled=True, owner_user_id=owner_id)
        db.add(instance)
        db.commit()
        refresh_tools(db, instance, notify=False)
        return instance.id


def test_按编号取东西的工具不在画板的工具清单里_工作流里照旧在(tmp_path: Path) -> None:
    from app.core.db import SessionLocal
    from app.domain.boards import producers
    from app.domain.workflows import available_node_types

    client = fresh_client()
    me = _me(client)
    _install(tmp_path)
    _connect(me)
    with SessionLocal() as db:
        listed = {one.id for one in producers.list_producers(db, me)}
        workflow_nodes = available_node_types(db, user_id=me)
    assert f"node:plugin.{PACKAGE}.paint" in listed
    assert PRODUCER not in listed and f"node:plugin.{PACKAGE}.recent" not in listed
    assert f"plugin.{PACKAGE}.fetch" in workflow_nodes and f"plugin.{PACKAGE}.recent" in workflow_nodes
    assert workflow_nodes[f"plugin.{PACKAGE}.fetch"]["config"]["fs_id"]["data_type"] == "external_id"


def test_存着的这种工具格跑的时候说清楚(tmp_path: Path) -> None:
    client = fresh_client()
    _install(tmp_path)
    _connect(_me(client))
    ws = _workspace(client)
    board_id = _action_board(client, ws, PRODUCER, config={"fs_id": "123"})
    refused = _run_tool(client, board_id, ws, PRODUCER, config={"fs_id": "123"})
    assert refused.status_code == 400, refused.text
    detail = refused.json()["detail"]
    assert "从网盘导入" in detail and "编号" in detail and "工作流" in detail, detail
    assert "不交出素材" not in detail, "它明明交出素材:说它按编号取东西,不说它不交出素材"


def test_对账把存着的工具格改成便签_线和产出都留着(tmp_path: Path) -> None:
    from app.core.db import SessionLocal
    from app.domain.boards import normalize_canvas
    from app.domain.boards.plugin_references import reconcile_plugin_tool_cells, retire_external_id_tools

    client = fresh_client()
    me = _me(client)
    _install(tmp_path)
    instance_id = _connect(me)
    ws = _workspace(client)
    fetch = {"config": {"fs_id": "123", "instance_id": instance_id}, "bindings": {}, "producer": PRODUCER}
    items = [
        {"id": "a1", "kind": "action", "x": 100, "y": 50, "width": 280, "height": 150, "title": "拉素材",
         "form": fetch, "run": {"status": "succeeded"}},
        {"id": "out", "kind": "note", "x": 500, "y": 50, "text": "上一轮取回的说明"},
        #: 在跑的那一格等它落终态。
        {"id": "a2", "kind": "action", "x": 100, "y": 400, "form": {**fetch, "config": {}},
         "run": {"status": "running", "job_id": "j1"}},
        #: 凭空产出的照旧是工具格。
        {"id": "a3", "kind": "action", "x": 100, "y": 700,
         "form": {"config": {}, "bindings": {}, "producer": f"node:plugin.{PACKAGE}.paint"}},
        #: 没有连接说得出它是什么的工具不动(跑的时候由注册表说清楚)。
        {"id": "a4", "kind": "action", "x": 100, "y": 1000,
         "form": {"config": {}, "bindings": {}, "producer": "node:plugin.dev.test.unknown.fetch"}},
    ]
    edges = [{"id": "e1", "source": "a1", "target": "out"}]
    created = client.post("/api/boards", json={"workspace_id": ws, "name": "B", "canvas": {"items": items, "edges": edges}})
    assert created.status_code == 200, created.text
    board_id, revision = created.json()["id"], created.json()["revision"]

    with SessionLocal() as db:
        reconcile_plugin_tool_cells(db)
        assert retire_external_id_tools(db) == 0, "改过的不再改:重复跑是安全的"

    board = client.get(f"/api/boards/{board_id}", params={"workspace_id": ws}).json()
    assert board["revision"] == revision + 1, "开着这张板的旧快照要撞 409,不能把工具格存回来"
    by_id = {one["id"]: one for one in board["canvas"]["items"]}
    note = by_id["a1"]
    assert {key: note[key] for key in ("kind", "x", "y", "width", "height", "title")} == {
        "kind": "note", "x": 100, "y": 50, "width": 280, "height": 150, "title": "拉素材"}
    assert note["form"] == {"producer": "write"} and "run" not in note
    assert "「从网盘导入」" in note["text"] and "工作流" in note["text"]
    assert '"fs_id": "123"' in note["text"], "原来的设置附在正文后面,不丢"
    assert "instance_id" not in note["text"], "选的连接是本机事实,不抄进正文"
    assert (by_id["out"]["kind"], by_id["out"]["text"]) == ("note", "上一轮取回的说明"), "它跑出来的产出一格不动"
    assert by_id["a2"]["kind"] == "action", "在跑的那一格不动"
    assert by_id["a3"]["kind"] == "action" and by_id["a4"]["kind"] == "action"
    assert board["canvas"]["edges"] == edges
    normalize_canvas(board["canvas"])


def test_对账挂在清单刷新之后和每次启动上() -> None:
    import inspect

    from app.domain.boards import plugin_references

    assert "retire_external_id_tools" in inspect.getsource(plugin_references.reconcile_plugin_tool_cells)
