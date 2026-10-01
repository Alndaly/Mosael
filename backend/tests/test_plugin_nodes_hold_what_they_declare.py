"""插件节点表单说的、运行时做的、下游拿到的,是同一件事。

- 数组入参(非素材)给「一串」编辑器,交给插件的是**数组**:此前当 object 给映射编辑器,存下去的是 `{"a": …}`。
- 自己写 `node.config` 的插件:是不是素材只听 input_schema(运行时就是按它换路径的)。
- 输出口叫 `artifact` / `artifacts` 的:宿主收产出时把它们换成了 `asset_id` / `asset_ids`,按口取值要到换过的名字上取。

装一个真的进程插件跑,不把 invoke / 执行器换掉。
"""

from __future__ import annotations

import textwrap
import time
from pathlib import Path

import pytest

from app.core.db import SessionLocal
from app.db.models import Job, PluginInstance, PluginPackage
from app.domain.plugins.nodes import node_meta
from app.domain.plugins.tools import refresh_tools
from app.domain.workflows import create_workflow
from app.domain.workflows.engine import start_workflow_job
from tests.util import fresh_client, user_id

PACKAGE = "dev.test.lister"
ENTRY = """
    import json, os, sys
    request = json.loads(sys.stdin.read())
    tool, given = request["tool"], request["input"]
    if tool == "join":
        print(json.dumps({"ok": True, "output": {
            "joined": "|".join(given.get("items") or []),
            "kinds": [type(one).__name__ for one in (given.get("sizes") or [])],
            "total": sum(given.get("sizes") or []),
        }}))
    elif tool == "echo":
        print(json.dumps({"ok": True, "output": {"got": given}}))
    else:
        open(os.path.join(os.environ["MOSAEL_PLUGIN_OUTPUT_DIR"], "out.txt"), "w").write("产出")
        print(json.dumps({"ok": True, "output": {"artifact": {"path": "out.txt"}, "caption": "一份产出"}}))
"""
TOOLS = [
    {
        "name": "join",
        "label": "拼起来",
        "input_schema": {"type": "object", "properties": {
            "items": {"type": "array", "items": {"type": "string"}, "title": "几段"},
            "sizes": {"type": "array", "items": {"type": "integer"}, "title": "几个数"},
            "steps": {"type": "array", "items": {"type": "object"}, "title": "几步"},
        }},
        "node": {"outputs": ["joined", "kinds", "total"]},
    },
    {
        "name": "echo",
        "label": "原样交回",
        "input_schema": {"type": "object", "properties": {
            "codes": {"type": "array", "items": {"type": "string"}},
            "ids": {"type": "array", "items": {"type": "integer"}},
            "flags": {"type": "array", "items": {"type": "boolean"}},
        }},
        "node": {"outputs": ["got"]},
    },
    {
        "name": "render",
        "label": "出一份",
        "input_schema": {"type": "object", "properties": {"img": {"type": "string", "format": "asset", "x-media": "image"}}},
        # 自己写 node.config,而且没标素材 —— 是不是素材听 input_schema 的
        "node": {"config": {"img": {"type": "template", "label": "参考图"}}, "outputs": ["artifact", "caption"]},
    },
]
RENDER = TOOLS[2]


def _install(tmp_path: Path, owner: str) -> str:
    plugin_dir = tmp_path / "lister"
    plugin_dir.mkdir(exist_ok=True)
    (plugin_dir / "main.py").write_text(textwrap.dedent(ENTRY), encoding="utf-8")
    manifest = {"id": PACKAGE, "name": "列表器", "version": "0.1.0", "runtime": {"kind": "process", "entry": "main.py"},
                "tools": {"expose": "all", "declare": TOOLS}, "_path": str(plugin_dir)}
    with SessionLocal() as db:
        db.add(PluginPackage(id=PACKAGE, name="列表器", version="0.1.0", manifest=manifest))
        db.flush()
        instance = PluginInstance(package_id=PACKAGE, name="我的列表器", enabled=True, owner_user_id=owner)
        db.add(instance)
        db.commit()
        refresh_tools(db, instance, notify=False)
        db.commit()
        return instance.id


def _run(ws: str, graph: dict, params: dict | None = None) -> tuple[str, dict, str | None]:
    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=ws, name="插件", graph=graph, created_by=user_id())
        db.commit()
        job_id = start_workflow_job(db, workflow, created_by=user_id(), params=params).id
    for _ in range(200):
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job.status in ("succeeded", "failed"):
                return job.status, job.result or {}, job.error
        time.sleep(0.05)
    raise AssertionError("工作流没跑完")


def _graph(node: dict) -> dict:
    return {"nodes": [{"id": "start", "type": "start", "config": {}}, node],
            "edges": [{"id": "e1", "source": "start", "target": node["id"]}]}


# ---------- 数组入参 ----------


def test_数组入参的表单是一串_不是映射() -> None:
    config = node_meta(TOOLS[0])["config"]
    assert config["items"]["type"] == "list" and "editor" not in config["items"]
    assert config["steps"]["type"] == "list" and config["steps"]["editor"] == "json"


def test_交给插件的是数组_一行是一整串引用时拼进来(tmp_path) -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    _install(tmp_path, user_id())
    status, result, error = _run(ws, _graph({
        "id": "j", "type": f"plugin.{PACKAGE}.join",
        "config": {"items": ["第一段", "{{start.more}}"], "sizes": ["1", "2"]},
    }), params={"more": ["第二段", "第三段"]})
    assert status == "succeeded", error
    assert result["context"]["j"] == {"joined": "第一段|第二段|第三段", "kinds": ["int", "int"], "total": 3}


def test_整格接上游的一段JSON数组文字也解开(tmp_path) -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    _install(tmp_path, user_id())
    status, result, error = _run(ws, _graph({
        "id": "j", "type": f"plugin.{PACKAGE}.join", "config": {"items": "{{start.raw}}"},
    }), params={"raw": '["x", "y"]'})
    assert status == "succeeded", error
    assert result["context"]["j"]["joined"] == "x|y"


def test_数组每一项按声明的类型交给插件_字符串项不改形(tmp_path) -> None:
    """表单只存文字(前端 ListField),类型由这里按 items.type 转:字符串项的 "007"、十九位 id 原样是字符串;
    整数项的长 id 不绕浮点数;布尔项的 true / false 是布尔。旧版表单存下的数(7)交给字符串项时写回文字。"""
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    _install(tmp_path, user_id())
    status, result, error = _run(ws, _graph({
        "id": "e", "type": f"plugin.{PACKAGE}.echo",
        "config": {"codes": ["007", "7342567890123457123", 7, True],
                   "ids": ["7342567890123457123", "2"], "flags": ["true", "false", " yes "]},
    }))
    assert status == "succeeded", error
    assert result["context"]["e"]["got"] == {
        "codes": ["007", "7342567890123457123", "7", "true"],
        "ids": [7342567890123457123, 2],
        "flags": [True, False, True],
    }


def test_数组入参收到名字到值的映射_报清楚是哪一格_不包成一项交给插件(tmp_path) -> None:
    """没被迁移到的旧写法 `{"a": …}`:此前被包成 `[{"a": …}]` 交给插件,插件那边莫名其妙地失败(这里的 join
    会在拼字符串时炸成一句 Python 原话)。现在交之前就说是哪一格、怎么改。"""
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    _install(tmp_path, user_id())
    status, _, error = _run(ws, _graph({
        "id": "j", "type": f"plugin.{PACKAGE}.join", "config": {"items": {"a": "第一段", "b": "第二段"}},
    }))
    assert status == "failed"
    assert "「几段」要的是一串值,收到的却是「名字 → 值」的映射" in (error or ""), error


@pytest.mark.xfail(strict=True, reason="必填的空值判据统一在 graph_rules(引擎那一轮修);合进来之后这条转绿,去掉这个标记")
def test_必填的数组入参填了空列表_运行前就拦() -> None:
    """插件的 list 字段和别的必填字段走同一个空值判据:`[]` 和没填一样。此前 graph_rules 只认 None / "",
    表单上一行都没填的必填数组放行,插件收到的是没有这一格(_as_list 把空列表去掉)。"""
    from app.domain.workflows.graph_rules import validate_graph

    tool = {"name": "t", "input_schema": {"type": "object", "required": ["items"], "properties": {
        "items": {"type": "array", "items": {"type": "string"}}}}}
    graph = _graph({"id": "p", "type": "plugin.pkg.t", "config": {"items": []}})
    errors = validate_graph(graph, extra_types={"plugin.pkg.t": node_meta(tool)})
    assert any("items" in one for one in errors), errors


# ---------- node.config 与 input_schema ----------


def test_自己写的node_config没标素材_照input_schema给素材选择器() -> None:
    img = node_meta(RENDER)["config"]["img"]
    assert img["data_type"] == "asset" and img["media"] == "image"
    assert img["label"] == "参考图"  # 自己写的标签照留


def test_node_config标了素材而input_schema没标_不给素材选择器() -> None:
    tool = {"name": "t", "input_schema": {"properties": {"img": {"type": "string"}}},
            "node": {"config": {"img": {"type": "template", "format": "asset", "data_type": "asset"}}}}
    assert "data_type" not in node_meta(tool)["config"]["img"]


# ---------- artifact 输出口 ----------


def test_输出口叫artifact的_下游拿到的是收进素材库的那一份(tmp_path) -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    _install(tmp_path, user_id())
    status, result, error = _run(ws, _graph({"id": "r", "type": f"plugin.{PACKAGE}.render", "config": {}}))
    assert status == "succeeded", error
    produced = result["context"]["r"]
    assert produced["caption"] == "一份产出"
    assert isinstance(produced["artifact"], str) and produced["artifact"], "artifact 口是空的"


def test_存成映射的数组入参_迁移成按顺序的值列表(tmp_path) -> None:
    from app.db.migrations import _migrate_plugin_array_inputs_are_lists
    from app.db.models import Workflow

    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    _install(tmp_path, user_id())
    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=ws, name="老流程", graph=_graph({
            "id": "j", "type": f"plugin.{PACKAGE}.join",
            "config": {"items": {"a": "第一段", "b": "{{start.x}}"}, "sizes": [1]},
        }), created_by=user_id())
        db.commit()
        workflow_id = workflow.id

    _migrate_plugin_array_inputs_are_lists()
    _migrate_plugin_array_inputs_are_lists()  # 再跑什么都不改

    with SessionLocal() as db:
        graph = db.get(Workflow, workflow_id).graph
        assert db.get(Workflow, workflow_id).revision == 2
    node = next(one for one in graph["nodes"] if one["id"] == "j")
    assert node["config"] == {"items": ["第一段", "{{start.x}}"], "sizes": [1]}


def test_老清单里node_config多标的素材_升级时去掉_升完装得上() -> None:
    """清单规则收紧(node.config 标了素材,input_schema 里也得是):装着的老清单要能被某一步改合格,否则读它就抛。"""
    from app.domain.plugins.manifest import parse
    from app.domain.plugins.migrations import upgrade

    raw = {"id": "a", "name": "n", "version": "1", "manifest_version": 4, "runtime": {"kind": "process", "entry": "m.py"},
           "tools": {"declare": [{"name": "t", "input_schema": {"type": "object", "properties": {
               "img": {"type": "string"}, "ok": {"type": "string", "format": "asset"}}},
               "node": {"config": {"img": {"type": "template", "format": "asset"}, "ok": {"format": "asset"}}}}]}}
    assert upgrade(raw)
    config = raw["tools"]["declare"][0]["node"]["config"]
    assert "format" not in config["img"], "从来没让插件收到过文件的那个标记去掉"
    assert config["ok"]["format"] == "asset", "两边一致的不动"
    parse(raw, "x")
