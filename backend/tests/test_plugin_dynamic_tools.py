"""插件在**运行时报出**的工具(`provides: ["tools"]`,见 domain/plugins/dynamic_tools)在宿主里:

- 报出来的工具和清单里声明的走同一条路:插件页的工具表(带和工作流节点同一份的表单字段)、智能体工具表、
  工作流节点类型(`plugin.<包>.<工具>`)、同一个执行入口;
- 刷新时机和生成模型目录一样,指纹变了自动刷新(catalog_watch 不认识具体能力);
- 清单格式不对 / 名字不合法 / 想认领宿主能力的,丢掉或记下原因,不拖垮别的;
- 存着的老 `run_workflow` 节点改写成取代它的那个工具(`replaces`),对不上的一格不丢,原样留着;
  启动时的对账步骤 `rewrite-replaced-plugin-tools` 用缓存的清单做同一件事。

用随应用发的 ComfyUI 插件 + 假 ComfyUI(tests/fake_comfyui)。
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import PluginInstance, PluginInvocation, PluginPackage, Workflow, WorkflowRevision
from tests.fake_comfyui import PNG, PORTRAIT_ID, UPSCALE_API, FakeComfyUI
from tests.util import fresh_client, user_id

PACKAGE = "dev.mosael.comfyui"
PORTRAIT_TOOL = "wf_" + PORTRAIT_ID.replace("-", "")[:12]


@pytest.fixture
def connected():
    with FakeComfyUI() as comfy:
        comfy.state.workflows["upscale.json"] = UPSCALE_API
        client = fresh_client()
        created = client.post(f"/api/plugins/{PACKAGE}/instances", json={"config": {"server_url": comfy.url}})
        assert created.status_code == 200, created.text
        instance_id = created.json()["id"]
        client.patch(f"/api/plugins/instances/{instance_id}/permissions", json={"grants": {"network:comfyui": True}})
        assert client.patch(f"/api/plugins/instances/{instance_id}", json={"enabled": True}).status_code == 200
        yield client, comfy, instance_id


def _instance(client) -> dict:
    return next(one for one in client.get("/api/plugins").json() if one["id"] == PACKAGE)["instances"][0]


def test_报出的工具出现在插件页_智能体和工作流里(connected) -> None:
    client, _, instance_id = connected
    instance = _instance(client)
    tools = {one["name"]: one for one in instance["tools"]}
    assert PORTRAIT_TOOL in tools and "comfyui_generation" not in tools
    portrait = tools[PORTRAIT_TOOL]
    assert portrait["label"] == "工作流 · portrait" and portrait["exposed"] is True, "每张工作流的工具默认开放"
    assert tools["run_workflow"]["exposed"] is False, "通用的 run_workflow 不再是主路径"
    form = portrait["form"]
    assert form["prompt"]["label"] == "提示词" and form["prompt"]["type"] == "template"
    assert form["image_10"]["data_type"] == "asset" and form["image_10"]["media"] == "image"
    assert form["steps_3"] == {**form["steps_3"], "label": "步数", "type": "number", "default": "20"}
    assert form["ckpt_name_4"]["options"] == ["sd_xl_base.safetensors", "v1-5.ckpt"]
    assert form["include_previews"]["option_labels"] == {"true": "是", "false": "否"}
    assert form["seed"]["advanced"] is True and "advanced" not in form["image_10"]
    assert "instance_id" not in form, "试跑就是在这个连接上"
    assert instance["capability_status"]["tools"]["tools"] == 3, "portrait、upscale、video/wan(没粘模板)"

    english = client.get("/api/plugins", headers={"Accept-Language": "en-US"}).json()
    en_tools = {one["name"]: one for one in next(p for p in english if p["id"] == PACKAGE)["instances"][0]["tools"]}
    assert en_tools[PORTRAIT_TOOL]["label"] == "Workflow · portrait" and en_tools[PORTRAIT_TOOL]["form"]["steps_3"]["label"] == "Steps"

    assert PORTRAIT_TOOL in {one["name"] for one in client.get("/api/plugins/tools").json() if one["instance_id"] == instance_id}
    node_types = {one["type"]: one for one in client.get("/api/workflows/node-types").json()}
    node = node_types[f"plugin.{PACKAGE}.{PORTRAIT_TOOL}"]
    assert node["label"] == "工作流 · portrait"
    assert "image_9" in node["outputs"] and node["output_types"]["image_9"] == "asset"


def test_跑报出的工具_素材进去_具名输出出来(connected) -> None:
    client, comfy, instance_id = connected
    comfy.state.outputs = {"9": {"images": [{"filename": "a.png", "type": "output"}, {"filename": "b.png", "type": "output"}]}}
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    source = client.post("/api/assets/import", data={"workspace_id": workspace},
                         files={"file": ("参考.png", PNG, "image/png")}).json()["id"]
    invoked = client.post(f"/api/plugins/instances/{instance_id}/tools/{PORTRAIT_TOOL}/invoke", json={
        "workspace_id": workspace, "input": {"prompt": "柴犬", "image_10": source, "steps_3": "12"},
    }).json()
    assert invoked["status"] == "succeeded", invoked
    output = invoked["output"]
    assert output["image_9"] == output["asset_ids"][0] == output["asset_id"], "那个保存节点的图就是具名输出 image_9"
    assert len(output["asset_ids"]) == 2
    prompt = comfy.posted("/prompt")[0]["prompt"]
    assert prompt["3"]["inputs"]["steps"] == 12


def test_目录变了自动刷新_生成模型和工具一起(connected) -> None:
    from app.domain.plugins import catalog_watch

    client, comfy, instance_id = connected
    with SessionLocal() as db:
        before = db.query(PluginInvocation).filter_by(instance_id=instance_id).count()
    assert catalog_watch.check_for_changes() == 0
    comfy.state.workflows["new.json"] = UPSCALE_API
    assert catalog_watch.check_for_changes() == 2, "模型目录和工具清单各刷一次"
    names = {one["name"] for one in _instance(client)["tools"]}
    assert any(name.startswith("wf_") and name != PORTRAIT_TOOL for name in names)
    with SessionLocal() as db:
        assert db.query(PluginInvocation).filter_by(instance_id=instance_id).count() == before + 2, "问指纹不留记录"


def _workflow(client, instance_id: str, ws: str, graph: dict) -> str:
    """老用户那里 run_workflow 是开着的(升级前它在推荐里),存着的节点才校验得过。"""
    from app.domain.workflows import create_workflow

    client.patch(f"/api/plugins/instances/{instance_id}/capabilities", json={"tools": {"run_workflow": True}})

    with SessionLocal() as db:
        return create_workflow(db, workspace_id=ws, name="老节点", graph=graph, created_by=user_id()).id


def test_老的run_workflow节点改写成那张工作流自己的工具(connected) -> None:
    from app.domain.workflows import plugin_references

    client, _, instance_id = connected
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    old = f"plugin.{PACKAGE}.run_workflow"
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "src", "type": "asset", "config": {"asset_id": "a1"}},
            {"id": "n1", "type": old, "config": {"workflow": "portrait.json", "prompt": "柴犬", "wait": True,
                                                  "values": {"3.steps": 30}, "images": []}},
            {"id": "n2", "type": old, "config": {"workflow": "portrait.json", "values": {"采样.steps": 3}}},
            {"id": "n3", "type": old, "config": {"workflow": "not-there.json"}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "n1"},
                  {"id": "e2", "kind": "data", "source": "src", "source_output": "asset_id", "target": "n1",
                   "target_input": "image"}],
    }
    workflow_id = _workflow(client, instance_id, ws, graph)
    with SessionLocal() as db:
        assert plugin_references.rewrite_replaced_tools(db) == 1
        workflow = db.get(Workflow, workflow_id)
        nodes = {node["id"]: node for node in workflow.graph["nodes"]}
        assert nodes["n1"]["type"] == f"plugin.{PACKAGE}.{PORTRAIT_TOOL}"
        assert nodes["n1"]["config"] == {"prompt": "柴犬", "steps_3": 30}, "wait: true 是老工具的默认,丢掉;空的也丢"
        assert nodes["n2"]["type"] == old, "按节点标题写的值对不上新工具的一格 —— 不丢用户的值,原样留着"
        assert nodes["n3"]["type"] == old, "不在清单里的工作流不动"
        [edge] = [edge for edge in workflow.graph["edges"] if edge.get("kind") == "data"]
        assert edge["target_input"] == "image_10", "连进来的数据边跟着改名"
        revisions = db.scalars(select(WorkflowRevision).where(WorkflowRevision.workflow_id == workflow_id)
                               .order_by(WorkflowRevision.revision)).all()
        assert revisions[-1].source == "migration" and revisions[-1].created_by == revisions[-2].created_by
        assert plugin_references.rewrite_replaced_tools(db) == 0, "再跑一次什么都不动"


def test_画板上的老工具格也改写过去(connected) -> None:
    """工具格(ADR 0021 P2)存的是 `node:<节点类型>` + 配置 + 绑定。绑定的字段名跟着改。"""
    from app.db.models import Board
    from app.domain.boards import plugin_references as board_references

    client, _, _ = connected
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    producer = f"node:plugin.{PACKAGE}.run_workflow"
    items = [
        {"id": "note", "kind": "note", "x": 0, "y": 0, "w": 100, "h": 100, "text": "柴犬"},
        {"id": "act", "kind": "action", "x": 200, "y": 0, "w": 100, "h": 100,
         "form": {"producer": producer, "config": {"workflow": "portrait.json", "values": {"3.cfg": 6}},
                  "bindings": {"prompt": [{"from": "note"}]}}},
        {"id": "odd", "kind": "action", "x": 400, "y": 0, "w": 100, "h": 100,
         "form": {"producer": producer, "config": {"workflow": "portrait.json"}, "bindings": {"values": [{"from": "note"}]}}},
    ]
    with SessionLocal() as db:
        board = Board(workspace_id=ws, name="画板", canvas={"items": items, "edges": []}, revision=3)
        db.add(board)
        db.commit()
        assert board_references.rewrite_replaced_tools(db) == 1
        db.refresh(board)
        by_id = {item["id"]: item for item in board.canvas["items"]}
        assert by_id["act"]["form"] == {"producer": f"node:plugin.{PACKAGE}.{PORTRAIT_TOOL}", "config": {"cfg_3": 6},
                                        "bindings": {"prompt": [{"from": "note"}]}}
        assert by_id["odd"]["form"]["producer"] == producer, "绑到对不上的字段:不动"
        assert board.revision == 4


def test_启动时的对账步骤用缓存的清单迁(connected) -> None:
    """`rewrite-replaced-plugin-tools`:ComfyUI 没开也迁得动(依据是上次缓存的工具清单)。"""
    from app.db.migrations import migration_plan

    client, comfy, instance_id = connected
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    workflow_id = _workflow(client, instance_id, ws, {"nodes": [
        {"id": "start", "type": "start", "config": {}},
        {"id": "n1", "type": f"plugin.{PACKAGE}.run_workflow", "config": {"workflow": "upscale.json", "image": "a1"}},
    ], "edges": [{"id": "e1", "source": "start", "target": "n1"}]})
    comfy.shutdown()
    [step] = [one for one in migration_plan().steps if one.name == "rewrite-replaced-plugin-tools"]
    assert step.once is False, "对账,每次启动都跑"
    step.operation()
    with SessionLocal() as db:
        node = next(one for one in db.get(Workflow, workflow_id).graph["nodes"] if one["id"] == "n1")
    assert node["type"].startswith(f"plugin.{PACKAGE}.wf_") and node["config"] == {"image_1": "a1"}


# --- 框架:别家插件报出的工具 ---------------------------------------------------------

ENTRY = """
import json, sys
request = json.loads(sys.stdin.read())
payload = request["input"]
if request["tool"] == "host" and payload.get("op") == "tools":
    tools = [
        {"name": "fine", "label": {"zh": "好的", "en": "Fine"}, "input_schema": {"type": "object", "properties": {
            "n": {"type": "integer", "title": {"zh": "次数", "en": "Times"}}}}, "recommended": True},
        {"name": "has.dot", "input_schema": {}},
        {"name": "host", "input_schema": {}},
        {"name": "sneaky", "provides": ["generation"], "internal": True},
    ]
    print(json.dumps({"ok": True, "output": {"tools": tools, "fingerprint": "v1"}}))
elif request["tool"] == "fine":
    print(json.dumps({"ok": True, "output": {"got": payload}}))
else:
    print(json.dumps({"ok": False, "error": "no"}))
"""


def test_报出的清单只收合法的_不能认领宿主能力(tmp_path: Path) -> None:
    from app.domain.plugins import host_capabilities
    from app.domain.plugins.tools import all_tools, invoke

    plugin_dir = tmp_path / "p"
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text(textwrap.dedent(ENTRY), encoding="utf-8")
    manifest = {"id": "dev.test.dynamic", "name": "动态", "version": "1.0.0", "manifest_version": 1,
                "runtime": {"kind": "process", "entry": "main.py"}, "provides": ["tools"],
                "tools": {"declare": [{"name": "host", "provides": ["tools"], "input_schema": {"type": "object"}}]}}
    fresh_client()
    with SessionLocal() as db:
        db.add(PluginPackage(id=manifest["id"], name="动态", version="1.0.0", manifest={**manifest, "_path": str(plugin_dir)}))
        db.flush()
        instance = PluginInstance(package_id=manifest["id"], name="动态", enabled=True, owner_user_id="")
        db.add(instance)
        db.commit()
        host_capabilities.notify(db, instance, refresh=True)
        db.refresh(instance)
        tools = {tool["name"]: tool for tool in all_tools(db, instance)}
        assert set(tools) == {"host", "fine", "sneaky"}, "带点的名字进不了节点类型;和声明重名的不收"
        assert tools["host"]["internal"] is True
        assert tools["sneaky"]["internal"] is False and tools["sneaky"]["provides"] == [], "报出的工具不能认领宿主能力"
        assert tools["fine"]["label"] == "好的"
        assert tools["fine"]["input_schema"]["properties"]["n"]["title"] == "次数"
        assert instance.capability_status["tools"]["fingerprint"] == "v1"
        invocation = invoke(db, instance.id, "fine", {"n": "3"})
        assert invocation.status == "succeeded" and invocation.output["got"] == {"n": 3}, "按入参声明把字符串转回数"
