"""插件工具被取代(`replaces`)时,改写不只管入参:**下游对它输出的引用**也要对得上。

此前只改节点自己和连进来的数据边。老 ComfyUI `run_workflow` 交 `assets` / `outputs`,取代它的 `wf_*` 工具没有这两个口:
改写之后,连出去的数据边找不到输出(绑定时静默跳过)、`{{n.assets}}` 取成空串,修订说明里一个字都没有。

现在:新工具有同名的口,或 `replaces.outputs` 写了改成哪个 → 跟着改;对不上的,老工具还在就不改这个节点,
不在了就改过去、连出去的那条线拆掉,都记进「丢掉」清单。
"""

from __future__ import annotations

from app.domain.workflows.plugin_references import Replacement, rewrite_graph

OLD = "plugin.dev.test.p.old"


def _replacement(*, retired: bool, outputs: dict | None = None) -> Replacement:
    spec = {"tool": "old", "rename": {"q": "prompt"}, **({"outputs": outputs} if outputs else {})}
    return Replacement("dev.test.p", "i1", "new", spec, {"prompt"}, retired=retired,
                       outputs=["asset_id", "asset_ids", "summary"])


def _graph() -> dict:
    return {
        "nodes": [
            {"id": "n", "type": OLD, "config": {"q": "猫"}},
            {"id": "use", "type": "template", "config": {"template": "{{n.summary}} / {{n.assets.0.asset_id}} / {{n.list}}"}},
            {"id": "loop", "type": "loop_foreach", "config": {"items": "{{n.assets}}"}},
        ],
        "edges": [
            {"id": "d1", "kind": "data", "source": "n", "source_output": "assets", "target": "loop", "target_input": "items"},
            {"id": "d2", "kind": "data", "source": "n", "source_output": "asset_id", "target": "use", "target_input": "x"},
        ],
    }


def test_老工具已经没了_对不上的下游引用和连线记进丢掉清单() -> None:
    dropped: list[str] = []
    rewritten = rewrite_graph(_graph(), [_replacement(retired=True)], dropped)
    nodes = {node["id"]: node for node in rewritten["nodes"]}
    assert nodes["n"]["type"] == "plugin.dev.test.p.new"
    assert {edge["id"] for edge in rewritten["edges"]} == {"d2"}, "新工具没有 assets 口:那条连出去的线拆掉"
    assert "n.assets(下游连线)" in dropped
    assert "n.assets(下游引用)" in dropped and "n.list(下游引用)" in dropped
    assert "n.summary(下游引用)" not in dropped, "新工具有同名的口,对得上"


def test_replaces写了输出改名_下游引用和连线跟着改() -> None:
    dropped: list[str] = []
    rewritten = rewrite_graph(
        _graph(), [_replacement(retired=True, outputs={"assets": "asset_ids", "list": "asset_ids"})], dropped
    )
    nodes = {node["id"]: node for node in rewritten["nodes"]}
    assert nodes["use"]["config"]["template"] == "{{n.summary}} / {{n.asset_ids.0.asset_id}} / {{n.asset_ids}}"
    assert nodes["loop"]["config"]["items"] == "{{n.asset_ids}}"
    edges = {edge["id"]: edge for edge in rewritten["edges"]}
    assert edges["d1"]["source_output"] == "asset_ids"
    assert dropped == []


def test_改了口名的引用带子路径_记进待核对清单() -> None:
    """`{{n.assets.0.asset_id}}` → `{{n.asset_ids.0.asset_id}}`:老口是一串对象、新口是一串 id,子路径对不上时
    取到的是空 —— 改写本身看不出来,此前一个字都不记。"""
    dropped: list[str] = []
    unchecked: list[str] = []
    rewrite_graph(_graph(), [_replacement(retired=True, outputs={"assets": "asset_ids", "list": "asset_ids"})],
                  dropped, unchecked)
    assert unchecked == ["{{n.assets.0.asset_id}} → {{n.asset_ids.0.asset_id}}"]
    assert dropped == []


def test_改写落修订时_带子路径的改名写进修订说明(tmp_path) -> None:
    """真库、真对账函数(rewrite_replaced_tools):修订说明里看得到哪几处要核对。"""
    from app.core.db import SessionLocal
    from app.db.models import PluginInstance, PluginPackage, WorkflowRevision
    from app.domain.workflows import create_workflow
    from app.domain.workflows.plugin_references import rewrite_replaced_tools
    from app.domain.workflows.revisions import current_workflow_revision, graph_digest
    from tests.util import fresh_client, user_id

    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    manifest = {"id": "dev.test.p", "name": "P", "version": "1", "runtime": {"kind": "process", "entry": "m.py"},
                "tools": {"expose": "all", "declare": [{"name": "old"}]}, "_path": str(tmp_path)}
    new_tool = {"name": "new", "input_schema": {"type": "object", "properties": {"prompt": {"type": "string"}}},
                "node": {"outputs": ["asset_ids", "summary"]},
                "replaces": {"tool": "old", "rename": {"q": "prompt"}, "outputs": {"assets": "asset_ids"}}}
    with SessionLocal() as db:
        db.add(PluginPackage(id="dev.test.p", name="P", version="1", manifest=manifest))
        db.flush()
        db.add(PluginInstance(package_id="dev.test.p", name="我的", enabled=True, owner_user_id=user_id(),
                              discovered_tools=[new_tool]))
        graph = {"nodes": [{"id": "start", "type": "start", "config": {}},
                           {"id": "n", "type": OLD, "config": {"q": "猫"}},
                           {"id": "use", "type": "template", "config": {"template": "{{n.assets.0.asset_id}}"}}],
                 "edges": [{"id": "e1", "source": "start", "target": "n"}]}
        # 老工具已经不是一个可用的节点了,建图的校验不认它:先建空图,再把老形状写进图和修订快照(同升级前存下的库)
        workflow = create_workflow(db, workspace_id=ws, name="老流程", created_by=user_id())
        db.commit()
        revision = current_workflow_revision(db, workflow)
        workflow.graph, revision.graph = graph, graph
        workflow.graph_hash = revision.graph_hash = graph_digest(graph)
        workflow_id = workflow.id
        db.commit()
        assert rewrite_replaced_tools(db) == 1
        note = db.query(WorkflowRevision).filter(WorkflowRevision.workflow_id == workflow_id).order_by(
            WorkflowRevision.revision.desc()).first().note
    assert "请核对" in note and "{{n.assets.0.asset_id}} → {{n.asset_ids.0.asset_id}}" in note, note


def test_老工具还在_下游对不上就不改这个节点() -> None:
    graph = _graph()
    rewritten = rewrite_graph(graph, [_replacement(retired=False)], [])
    assert rewritten["nodes"][0]["type"] == OLD, "宁可留着能跑的老节点,也不让下游安静地取到空"
    assert rewritten["edges"] == graph["edges"]


def test_下游都对得上时_老工具还在也照改() -> None:
    graph = _graph()
    graph["nodes"] = graph["nodes"][:1] + [{"id": "use", "type": "template", "config": {"template": "{{n.summary}}"}}]
    graph["edges"] = [graph["edges"][1]]
    rewritten = rewrite_graph(graph, [_replacement(retired=False)], [])
    assert rewritten["nodes"][0]["type"] == "plugin.dev.test.p.new"


# ---------- 作用域:容器的 output / condition 属于体内 ----------


def test_体里的节点改了口名_容器自己的output和condition跟着改() -> None:
    """循环体里的老节点被改写时,父容器的 output / condition 是体内的下游(它们在体内作用域里插值):
    此前递归进体时只扫体里的节点,看不到这两格 —— 口改了名,`{{n.assets}}` 留着取空。"""
    body = {"nodes": [{"id": "n", "type": OLD, "config": {"q": "猫"}}], "edges": []}
    graph = {"nodes": [{"id": "loop", "type": "loop_while", "config": {
        "body": body, "output": "{{n.assets}}", "condition": "{{n.assets}}", "max_iterations": "3"}}], "edges": []}
    dropped: list[str] = []
    rewritten = rewrite_graph(graph, [_replacement(retired=True, outputs={"assets": "asset_ids"})], dropped)
    loop = rewritten["nodes"][0]["config"]
    assert loop["body"]["nodes"][0]["type"] == "plugin.dev.test.p.new"
    assert loop["output"] == "{{n.asset_ids}}" and loop["condition"] == "{{n.asset_ids}}"
    assert dropped == []


def test_体里的节点_容器output引用了新工具没有的口_老工具还在就不改() -> None:
    body = {"nodes": [{"id": "n", "type": OLD, "config": {"q": "猫"}}], "edges": []}
    graph = {"nodes": [{"id": "loop", "type": "loop_foreach", "config": {
        "items": "[1]", "body": body, "output": "{{n.list}}"}}], "edges": []}
    rewritten = rewrite_graph(graph, [_replacement(retired=False)], [])
    assert rewritten["nodes"][0]["config"]["body"]["nodes"][0]["type"] == OLD, "output 要的口新工具没有:不改"


def test_外层同名节点_不把容器体内的output当成自己的下游() -> None:
    """外层的 n 和体里的 n 同名是常态(节点 id 只在一层里唯一)。容器的 output 指的是体里那个:
    此前外层扫描把它算成外层 n 的下游 —— 要么因为「对不上」不改外层节点,要么把体内的引用改了名。"""
    body = {"nodes": [{"id": "n", "type": "llm", "config": {"prompt": "hi"}}], "edges": []}
    graph = {"nodes": [
        {"id": "n", "type": OLD, "config": {"q": "猫"}},
        {"id": "use", "type": "template", "config": {"template": "{{n.assets}}"}},
        {"id": "loop", "type": "loop_foreach", "config": {"items": "[1]", "body": body, "output": "{{n.text}} {{n.assets}}"}},
    ], "edges": []}
    dropped: list[str] = []
    rewritten = rewrite_graph(graph, [_replacement(retired=False, outputs={"assets": "asset_ids"})], dropped)
    nodes = {node["id"]: node for node in rewritten["nodes"]}
    assert nodes["n"]["type"] == "plugin.dev.test.p.new", "体内的 {{n.text}} 不是外层 n 的下游"
    assert nodes["use"]["config"]["template"] == "{{n.asset_ids}}"
    assert nodes["loop"]["config"]["output"] == "{{n.text}} {{n.assets}}", "体内的引用不跟着外层改名"
    assert dropped == []
