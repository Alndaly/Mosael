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
            "nums": {"type": "array", "items": {"type": "number"}},
            "words": {"type": "array", "items": {"type": "string"}},
            "objs": {"type": "array", "items": {"type": "object"}},
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


def test_数组入参的边界_一行JSON数组文字拼进来_逗号不拆_nan不转_对象文字解开(tmp_path) -> None:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    _install(tmp_path, user_id())
    status, result, error = _run(ws, _graph({
        "id": "e", "type": f"plugin.{PACKAGE}.echo",
        "config": {"codes": ["{{start.llm}}", "c"], "words": "a, b", "nums": ["nan", "inf", "1.5"],
                   "objs": ['{"k": 1}', "{{start.obj}}"]},
    }), params={"llm": '["a", "b"]', "obj": {"k": 2}})
    assert status == "succeeded", error
    got = result["context"]["e"]["got"]
    assert got["codes"] == ["a", "b", "c"], "一行拿到的 JSON 数组文字和整格一样拼进来"
    assert got["words"] == ["a, b"], "逗号分隔的文字不拆"
    assert got["nums"] == ["nan", "inf", 1.5], "nan / inf 不是谁填的数"
    assert got["objs"] == [{"k": 1}, {"k": 2}], "每一项是对象的,JSON 对象文字解开成那一项"
    status, result, error = _run(ws, _graph({
        "id": "e", "type": f"plugin.{PACKAGE}.echo", "config": {"objs": "{{start.obj}}"},
    }), params={"obj": '{"k": 3}'})
    assert status == "succeeded", error
    assert result["context"]["e"]["got"]["objs"] == [{"k": 3}], "整格接一段 JSON 对象文字:就是那一项"


# ---------- node.config 与 input_schema ----------


def test_自己写的node_config没标素材_照input_schema给素材选择器() -> None:
    img = node_meta(RENDER)["config"]["img"]
    assert img["data_type"] == "asset" and img["media"] == "image"
    assert img["label"] == "参考图"  # 自己写的标签照留


def test_node_config标了素材而input_schema没标_不给素材选择器() -> None:
    tool = {"name": "t", "input_schema": {"properties": {"img": {"type": "string"}}},
            "node": {"config": {"img": {"type": "template", "format": "asset", "data_type": "asset"}}}}
    assert node_meta(tool)["config"]["img"]["data_type"] == "any"


def test_插件字段叫asset_id也不按名字推成素材_只听schema的format() -> None:
    """内置节点那套「asset_id → 素材」的命名约定不套到插件上:插件的 `asset_id` 可能是别的系统里的编号。
    此前按名字推成素材 —— 表单给素材选择器、画板只接媒体格,运行时却不换路径(asset_fields 只听 format)。"""
    from app.domain.boards.tools import bindable_kinds
    from app.domain.plugins.inputs import asset_fields
    from app.domain.workflows.node_catalog import with_data_type

    tool = {"name": "t", "input_schema": {"type": "object", "properties": {
        "asset_id": {"type": "string", "description": "远端系统里的编号"},
        "ref_asset_ids": {"type": "array", "items": {"type": "string"}},
        "real": {"type": "string", "format": "asset"}}}}
    config = node_meta(tool)["config"]
    assert asset_fields(tool) == ["real"]
    for key in ("asset_id", "ref_asset_ids"):
        assert with_data_type(key, config[key])["data_type"] == "any", key
        assert "image" not in bindable_kinds(key, config[key]), key
    assert with_data_type("real", config["real"])["data_type"] == "asset"


def test_node_config说一串而schema不是数组_降回schema那一格的样子() -> None:
    """运行时只按 schema 把文字转成数组(inputs.coerce);node.config 自己写 list / asset_list 而 schema 是字符串,
    表单存下一个列表、插件收到的也是列表 —— 和它声明的字符串对不上。"""
    tool = {"name": "t", "input_schema": {"type": "object", "properties": {"x": {"type": "string"}, "n": {"type": "integer"}}},
            "node": {"config": {"x": {"type": "asset_list", "label": "X"}, "n": {"type": "list", "editor": "json"},
                                "ghost": {"type": "list"}}}}
    config = node_meta(tool)["config"]
    assert config["x"]["type"] == "template" and config["x"]["label"] == "X"
    assert config["n"]["type"] == "number" and "editor" not in config["n"]
    assert config["ghost"]["type"] == "template", "schema 里没有这一格:一段文字"


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
