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
