"""代码字段(「执行脚本」的 expression、「代码」节点的 code)不插值,所以:

- 不能接数据边:上游的值整段变成代码,和把 {{}} 拼进去是同一个注入 —— 运行前校验拦下,说清该接到 input;
- 里面残留的 `{{…}}` 不是引用:不算依赖(不排先后、不成环)、不查作用域、规范化也不把它变成数据边。
"""

from __future__ import annotations

from app.domain.workflows import NODE_TYPES, reference_dependencies, validate_body_graph, validate_graph
from app.domain.workflows.normalization import normalize_graph


def _graph(*nodes: dict, edges: list | None = None) -> dict:
    return {"nodes": [{"id": "start", "type": "start", "config": {}}, *nodes], "edges": edges or []}


def _data_edge(source: str, output: str, target: str, field: str) -> dict:
    return {"id": f"{source}-{target}", "kind": "data", "source": source, "source_output": output,
            "target": target, "target_input": field}


def test_数据边连进代码字段_运行前拦下() -> None:
    graph = _graph(
        {"id": "llm", "type": "template", "config": {"template": "x"}},
        {"id": "js", "type": "browser_evaluate", "config": {"session": "s"}},
        edges=[_data_edge("llm", "text", "js", "expression")],
    )
    errors = validate_graph(graph)
    assert any("js" in e and "expression" in e and "input" in e for e in errors), errors


def test_接到入参上的上游值照常() -> None:
    graph = _graph(
        {"id": "llm", "type": "template", "config": {"template": "x"}},
        {"id": "js", "type": "browser_evaluate",
         "config": {"session": "s", "expression": "input.t", "input": {"t": "{{llm.text}}"}}},
    )
    assert validate_graph(graph) == []


def test_代码里残留的引用不算依赖_不成环() -> None:
    graph = _graph(
        {"id": "a", "type": "code", "config": {"code": "output = '{{b.text}}'"}},
        {"id": "b", "type": "template", "config": {"template": "{{a.output}}"}},
    )
    assert reference_dependencies(graph)["a"] == set()
    assert not any("环" in e for e in validate_graph(graph))


def test_体里的代码引用体外_不当越界() -> None:
    body = {"nodes": [{"id": "n1", "type": "code", "config": {"code": "x = '{{start.prefix}}'"}}], "edges": []}
    assert validate_body_graph(body, "loop_foreach") == []


def test_规范化不把代码字段里的整格引用变成数据边() -> None:
    graph = _graph(
        {"id": "llm", "type": "template", "config": {"template": "x"}},
        {"id": "js", "type": "browser_evaluate", "config": {"session": "s", "expression": "{{llm.text}}"}},
    )
    normalized = normalize_graph(graph, node_types=NODE_TYPES)
    assert not [edge for edge in normalized["edges"] if edge.get("kind") == "data"]
    js = next(node for node in normalized["nodes"] if node["id"] == "js")
    assert js["config"]["expression"] == "{{llm.text}}"
