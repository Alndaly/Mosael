"""插件节点的名字跟着插件报的名字走(迁移 `migrate-plugin-node-names-follow-the-plugin`)。

维护者:同一张 ComfyUI 工作流,模型下拉里叫精简表单的标题,画布上的节点却还叫「工作流 · 文件名」—— 「添加节点」把
插件工具当时的名字写进了节点。现在加节点不写死(前端 newNode);存着的节点由这条迁移跟上:名字就是那个工具在升级前
缓存的清单里的名字(中文、英文都算)的,清掉;用户改过的名字、认不出工具的节点不动。改了的图落一版修订,作者照旧。
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.migrations import _migrate_plugin_node_names_follow_the_plugin
from app.db.models import Workflow, WorkflowRevision
from tests.test_plugin_dynamic_tools import PACKAGE, PORTRAIT_TOOL, _workflow, connected  # noqa: F401 — connected 是夹具


def test_写死的插件工具名字清掉_用户改过的名字留着(connected) -> None:  # noqa: F811
    client, _, _ = connected
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    kind = f"plugin.{PACKAGE}.{PORTRAIT_TOOL}"
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "name": "开始", "config": {}},
            {"id": "zh", "type": kind, "name": "工作流 · portrait", "config": {}},
            {"id": "en", "type": kind, "name": "Workflow · portrait", "config": {}},
            {"id": "mine", "type": kind, "name": "我的人像", "config": {}},
            {"id": "other", "type": "llm", "name": "工作流 · portrait", "config": {}},
            {"id": "gone", "type": f"plugin.{PACKAGE}.wf_000000000000", "name": "工作流 · 删掉的", "config": {}},
            {"id": "each", "type": "loop_foreach", "name": "逐张", "config": {"items": "a", "body": {
                "nodes": [{"id": "inner", "type": kind, "name": "工作流 · portrait", "config": {}}], "edges": []}}},
        ],
        "edges": [],
    }
    workflow_id = _workflow(ws, graph)

    _migrate_plugin_node_names_follow_the_plugin()
    _migrate_plugin_node_names_follow_the_plugin()  # 再跑什么都不改

    with SessionLocal() as db:
        workflow = db.get(Workflow, workflow_id)
        nodes = {node["id"]: node for node in workflow.graph["nodes"]}
        revisions = db.query(WorkflowRevision).filter_by(workflow_id=workflow_id).count()
    assert "name" not in nodes["zh"] and "name" not in nodes["en"], "就是插件起的名字:清掉,跟着插件报的走"
    assert "name" not in nodes["each"]["config"]["body"]["nodes"][0], "循环体里的一样"
    assert nodes["mine"]["name"] == "我的人像", "用户改过的名字是用户的"
    assert nodes["other"]["name"] == "工作流 · portrait", "不是插件节点的不碰"
    assert nodes["gone"]["name"] == "工作流 · 删掉的", "认不出工具的节点不动"
    assert nodes["start"]["name"] == "开始"
    assert revisions == 2, "改了一次,落一版修订;再跑不再落"
