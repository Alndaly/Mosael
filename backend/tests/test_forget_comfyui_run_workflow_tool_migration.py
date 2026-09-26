"""`forget-comfyui-run-workflow-tool`:ComfyUI 插件删掉了通用的 `run_workflow`,只挂着这个工具名的东西清掉。

它不知道要跑哪张工作流,表单却要人填参数;它能跑的每一种图都有了自己的工具。存着的节点由对账
`rewrite-replaced-plugin-tools` 按插件报出的清单改(见 test_plugin_dynamic_tools);这一步清的是不用等清单的:

- `plugin_capabilities` 里 ComfyUI 连接上 `run_workflow` 的开关(别的工具、别的插件的同名工具不碰);
- 会话「本会话始终允许」里的 `plugin__<ComfyUI 连接>__run_workflow`(别的名字原样留着)。

再跑一次什么都不动。
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.migrations import _forget_comfyui_run_workflow_tool as migrate, migration_plan
from app.db.models import AgentSession, PluginCapability, PluginInstance, PluginPackage
from tests.util import fresh_client, user_id

COMFYUI = "dev.mosael.comfyui"


def test_是一次性迁移_排在对账之前() -> None:
    names = [step.name for step in migration_plan().steps]
    [step] = [one for one in migration_plan().steps if one.name == "forget-comfyui-run-workflow-tool"]
    assert step.once is True
    assert names.index("forget-comfyui-run-workflow-tool") < names.index("rewrite-replaced-plugin-tools")
    assert names.index("install-bundled-plugins") < names.index("forget-comfyui-run-workflow-tool")


def test_清掉run_workflow的开关和会话放行_别的不碰_再跑一次不动() -> None:
    client = fresh_client()
    me = user_id("tester")
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        if db.get(PluginPackage, COMFYUI) is None:
            db.add(PluginPackage(id=COMFYUI, name="ComfyUI", version="1.3.0", manifest={}))
        db.add(PluginPackage(id="dev.example.other", name="Other", version="1.0.0", manifest={}))
        db.flush()
        db.add_all([
            PluginInstance(id="comfy1", owner_user_id=me, package_id=COMFYUI, name="C"),
            PluginInstance(id="other1", owner_user_id=me, package_id="dev.example.other", name="O"),
        ])
        db.flush()
        db.add_all([
            PluginCapability(instance_id="comfy1", tool_name="run_workflow", exposed=True),
            PluginCapability(instance_id="comfy1", tool_name="list_workflows", exposed=True),
            PluginCapability(instance_id="other1", tool_name="run_workflow", exposed=True),
        ])
        allowed = ["plugin__comfy1__run_workflow", "plugin__comfy1__wf_abc", "plugin__other1__run_workflow",
                   "generate_image"]
        db.add_all([
            AgentSession(id="s1", workspace_id=ws, owner_user_id=me, title="会话", auto_allow_tools=allowed),
            AgentSession(id="s2", workspace_id=ws, owner_user_id=me, title="另一个", auto_allow_tools=["generate_image"]),
        ])
        db.commit()

    migrate()
    migrate()

    with SessionLocal() as db:
        switches = {(row.instance_id, row.tool_name) for row in db.scalars(select(PluginCapability))
                    if row.instance_id in ("comfy1", "other1")}
        assert switches == {("comfy1", "list_workflows"), ("other1", "run_workflow")}, (
            "只清 ComfyUI 连接上的 run_workflow;别家插件的同名工具是另一回事")
        assert db.get(AgentSession, "s1").auto_allow_tools == [
            "plugin__comfy1__wf_abc", "plugin__other1__run_workflow", "generate_image"], (
            "允许过「按 id 跑任意一张」不等于允许过哪一张:不转给每张图的工具,直接去掉")
        assert db.get(AgentSession, "s2").auto_allow_tools == ["generate_image"]
