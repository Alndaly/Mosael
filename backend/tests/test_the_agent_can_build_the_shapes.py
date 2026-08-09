"""智能体建得出**并排**和**内嵌**的工作流吗 —— 先确认路是通的,再谈它想不想走。

用户观察到:工作流智能体几乎只画一条直线,很少用并排分支、子图、调用工作流。这有两种可能的原因,
方向完全相反:

  一、路不通 —— `edit_workflow` 表达不了这些形状(嵌套 config 被过滤掉、并排边被拒),
      那么改提示词一点用都没有;
  二、路通,但它想不到 —— 那就是提示词的问题。

前半份钉的是第一种:**通过智能体那条唯一的写入路径**(edit_workflow 的 add_node/connect)把三种
形状建出来,并且过得了校验。跑下来**三种都建得出** —— 所以路是通的,问题在第二种。

后半份钉的就是第二种。查下来"并排""子图""调用工作流"这三件事,在智能体每轮都读得到的两处
(系统提示、edit_workflow 的工具说明)里**一个字都没有**:提示词只讲了"改画布用哪个工具",
工具说明只给了一条直线的例子。节点清单里倒是有,但那要它先想到去列一遍,而想不到正是问题本身。

**能力不写在它读得到的地方,等于没有这个能力。**
"""

from __future__ import annotations

from app.domain.workflows import validate_graph
from app.domain.workflows.graph_ops import apply_graph_ops

EMPTY: dict = {"nodes": [], "edges": []}


def _built(operations: list[dict]) -> dict:
    """走智能体那条唯一的写入路径,并且**跑一遍校验** —— 存得进去才算建得出来。"""
    graph = apply_graph_ops(EMPTY, operations)
    errors = validate_graph(graph)
    assert not errors, f"建出来的图过不了校验:{errors}"
    return graph


def test_it_can_fan_out_into_parallel_branches() -> None:
    """一个节点接出两条边 = 两支并排跑(引擎确实并发,见 engine.MAX_PARALLEL_NODES)。"""
    graph = _built([
        {"kind": "add_node", "type": "start", "node_id": "start_1"},
        {"kind": "add_node", "type": "template", "node_id": "a", "config": {"template": "左"}},
        {"kind": "add_node", "type": "template", "node_id": "b", "config": {"template": "右"}},
        {"kind": "connect", "source": "start_1", "target": "a"},
        {"kind": "connect", "source": "start_1", "target": "b"},
    ])

    outgoing = [e for e in graph["edges"] if e["source"] == "start_1"]
    assert len(outgoing) == 2, f"并排的两条边没存下来:{graph['edges']}"


def test_it_can_nest_a_subgraph_with_a_body() -> None:
    """子图的 body 是**嵌套的节点数组** —— 最容易被 config 处理吃掉的那种形状。"""
    graph = _built([
        {"kind": "add_node", "type": "start", "node_id": "start_1"},
        {
            "kind": "add_node",
            "type": "subgraph",
            "node_id": "sub_1",
            "config": {
                "inputs": {"名字": "{{start_1.text}}"},
                "body": {
                    "nodes": [{"id": "inner_1", "type": "template", "config": {"template": "你好 {{input.名字}}"}}],
                    "edges": [],
                },
                "output": "{{inner_1.text}}",
            },
        },
        {"kind": "connect", "source": "start_1", "target": "sub_1"},
    ])

    node = next(n for n in graph["nodes"] if n["id"] == "sub_1")
    assert node["config"]["body"]["nodes"][0]["id"] == "inner_1", f"嵌套 body 没留住:{node['config']}"
    assert node["config"]["output"] == "{{inner_1.text}}"


def test_it_can_call_another_workflow() -> None:
    """调用工作流:另一张图当子流程,拿它「输出」节点声明的结果。"""
    graph = _built([
        {"kind": "add_node", "type": "start", "node_id": "start_1"},
        {"kind": "add_node", "type": "call_workflow", "node_id": "call_1",
         "config": {"workflow_id": "wf-callee", "inputs": {}}},
        {"kind": "connect", "source": "start_1", "target": "call_1"},
    ])

    node = next(n for n in graph["nodes"] if n["id"] == "call_1")
    assert node["config"]["workflow_id"] == "wf-callee"


def test_the_node_catalogue_tells_the_agent_these_exist() -> None:
    """智能体是从这份清单认识节点的 —— 三种形状都得在里面,而且描述要说清什么时候用。"""
    from app.domain.workflows import NODE_TYPES

    assert NODE_TYPES["subgraph"]["description"], "子图没有描述,智能体只能靠名字猜"
    assert NODE_TYPES["call_workflow"]["description"]


# ---------------- 它读得到吗 ----------------


def _agent_facing_text() -> str:
    """智能体每轮都读得到的那两处:系统提示 + edit_workflow 的工具说明。

    节点清单(list_workflow_node_types)不算:那要它先想到去列一遍,而"想不到"正是要修的东西。
    """
    import pathlib

    import mcp_server
    from app.ai.agent.host import SYSTEM_PROMPT_TEMPLATE

    del pathlib
    return SYSTEM_PROMPT_TEMPLATE + (mcp_server.edit_workflow.__doc__ or "")


def test_it_is_told_that_branches_run_side_by_side() -> None:
    """一个节点接出多条边就是并排跑 —— 不说的话,模型默认画一条直线。"""
    assert "并排" in _agent_facing_text()


def test_it_is_told_that_subgraphs_and_called_workflows_exist() -> None:
    """两种"内嵌"各有各的场合:一次性的复杂段落折成子图,复用的段落抽成独立工作流去调。"""
    text = _agent_facing_text()

    assert "subgraph" in text, "子图没出现在它读得到的地方"
    assert "call_workflow" in text, "调用工作流没出现在它读得到的地方"
