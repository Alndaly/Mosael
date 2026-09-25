"""Canonical workflow graph shapes shared by every persistence entry point.

An exact ``{{node.output}}`` value is a data dependency, not a manually entered literal.  Keeping
it in ``config`` made resource fields render as workspace selectors and hid the real dependency
behind an ordinary control edge.  This module upgrades that unambiguous shorthand to the native
data-edge representation while leaving composite templates and nested output paths untouched.
"""

from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

PURE_REFERENCE_RE = re.compile(r"\{\{\s*([\w.-]+)\s*\}\}")


def normalize_graph(graph: dict[str, Any], *, node_types: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """**图的规范形状**:保存、导入、官方模板、迁移都经过这一个入口。

    两件事:声明为「行列表」的字段统一成列表(见 canonicalize_line_fields),精确的
    `{{节点.输出}}` 升级成数据边(见 canonicalize_data_bindings)。库里只存规范形状,
    读取端和编辑器因此只认一种。
    """
    return canonicalize_data_bindings(canonicalize_line_fields(graph, node_types=node_types), node_types=node_types)


def canonicalize_line_fields(graph: dict[str, Any], *, node_types: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """声明了 `"lines": True` 的字段,值统一成**行的列表**(一段多行文本按行拆开)。

    为什么要是列表:某一行可以正好是一整串引用(`{{角色三视图.results}}`),插值后是一组值,
    解析时摊平 —— 全部角色的三视图一次接进参考图。存成一整段多行文本的话,这一行在插值时
    和别的行拼在同一个字符串里,列表被 `str()` 成 `['…', '…']`,当场就坏。
    """
    normalized = deepcopy(graph)
    _lines_in(normalized, node_types)
    return normalized


def _lines_in(graph: dict[str, Any], node_types: dict[str, dict[str, Any]]) -> None:
    for node in graph.get("nodes") or []:
        if not isinstance(node, dict):
            continue
        config = node.get("config")
        if not isinstance(config, dict):
            continue
        specs = (node_types.get(str(node.get("type", ""))) or {}).get("config") or {}
        for key, spec in specs.items():
            if isinstance(spec, dict) and spec.get("lines") and isinstance(config.get(key), str):
                config[key] = [line.strip() for line in config[key].splitlines() if line.strip()]
        body = config.get("body")
        if isinstance(body, dict) and isinstance(body.get("nodes"), list):
            _lines_in(body, node_types)


def canonicalize_data_bindings(
    graph: dict[str, Any],
    *,
    node_types: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return a copy with exact node-output references represented as typed data edges.

    Only a top-level scalar config value with exactly two path components is losslessly
    representable by the current edge contract.  ``{{node.json.items}}`` and strings that combine
    prose with references therefore stay as templates.  Nested workflow bodies are normalized by
    the same rules, in their own scope.
    """

    normalized = deepcopy(graph)
    _canonicalize_graph(normalized, node_types)
    return normalized


def _canonicalize_graph(graph: dict[str, Any], node_types: dict[str, dict[str, Any]]) -> None:
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    # Validation owns malformed input.  Normalization must never make a broken payload valid by
    # silently dropping its bad members or inventing missing containers.
    if (
        not isinstance(nodes, list)
        or not isinstance(edges, list)
        or any(not isinstance(node, dict) for node in nodes)
        or any(not isinstance(edge, dict) for edge in edges)
    ):
        return

    by_id = {str(node.get("id", "")): node for node in nodes}
    bound_inputs = {
        (str(edge.get("target", "")), str(edge.get("target_input", ""))): edge
        for edge in edges
        if edge.get("kind") == "data" and edge.get("target_input")
    }
    inputs_by_target: dict[str, list[str]] = {}
    for target_id, input_key in bound_inputs:
        inputs_by_target.setdefault(target_id, []).append(input_key)
    new_bindings: list[tuple[str, str, str, str]] = []

    for target in nodes:
        target_id = str(target.get("id", ""))
        metadata = node_types.get(str(target.get("type", ""))) or {}
        config_specs = metadata.get("config") or {}
        config = target.get("config")
        if not target_id or not isinstance(config, dict) or not isinstance(config_specs, dict):
            continue

        raw_connected_inputs = target.get("inputs")
        connected_inputs = (
            [str(key) for key in raw_connected_inputs if str(key)]
            if isinstance(raw_connected_inputs, list)
            else []
        )
        for input_key in inputs_by_target.get(target_id, []):
            if input_key not in connected_inputs:
                connected_inputs.append(input_key)
        for input_key, value in config.items():
            spec = config_specs.get(input_key)
            if not isinstance(spec, dict) or spec.get("type") in {"object", "graph"}:
                continue
            if not isinstance(value, str):
                continue
            match = PURE_REFERENCE_RE.fullmatch(value.strip())
            if match is None:
                continue
            reference = match.group(1).split(".")
            if len(reference) != 2:
                continue
            source_id, source_output = reference
            source = by_id.get(source_id)
            source_metadata = node_types.get(str(source.get("type", ""))) if source else None
            outputs = source_metadata.get("outputs", []) if source_metadata else []
            if source_id == target_id or source_output not in outputs:
                continue

            binding_key = (target_id, input_key)
            if binding_key not in bound_inputs:
                new_bindings.append((source_id, source_output, target_id, input_key))
            if input_key not in connected_inputs:
                connected_inputs.append(input_key)
            config[input_key] = ""

        if connected_inputs:
            target["inputs"] = connected_inputs

        body = config.get("body")
        if isinstance(body, dict) and isinstance(body.get("nodes"), list):
            _canonicalize_graph(body, node_types)

    connected_pairs = {
        (str(edge.get("source", "")), str(edge.get("target", "")))
        for edge in edges
        if edge.get("kind") == "data"
    } | {(source, target) for source, _, target, _ in new_bindings}

    def routes(edge: dict[str, Any]) -> bool:
        """这条控制边带路由语义吗:从会分支的节点出发的,没写 handle 也是「真」那一支。"""
        source = by_id.get(str(edge.get("source", "")))
        source_type = str(source.get("type", "")) if source else ""
        return bool((node_types.get(source_type) or {}).get("branches"))

    if connected_pairs:
        # 同一对节点间已有数据边时,无 handle 的控制边只剩"排先后"一个作用,而数据边本身就排先后
        # —— 可以折掉。带路由语义的不行:折掉它等于把"只在真时跑"改成"总是跑"。
        edges[:] = [
            edge
            for edge in edges
            if not (
                edge.get("kind", "control") == "control"
                and not edge.get("source_handle")
                and not routes(edge)
                and (str(edge.get("source", "")), str(edge.get("target", ""))) in connected_pairs
            )
        ]

    used_ids = {str(edge.get("id", "")) for edge in edges}
    for source_id, source_output, target_id, target_input in new_bindings:
        edge_id = f"d-{source_id}-{source_output}-{target_id}-{target_input}"
        if edge_id in used_ids:
            suffix = 2
            while f"{edge_id}-{suffix}" in used_ids:
                suffix += 1
            edge_id = f"{edge_id}-{suffix}"
        used_ids.add(edge_id)
        edges.append(
            {
                "id": edge_id,
                "source": source_id,
                "target": target_id,
                "kind": "data",
                "source_output": source_output,
                "target_input": target_input,
            }
        )
