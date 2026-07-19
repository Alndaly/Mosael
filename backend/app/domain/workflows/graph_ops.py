"""Granular workflow-graph edits.

The agent expresses INTENT as a list of small ops (add a node, connect A→B, set a
config field) and the server materializes them onto the current graph. This replaces
the old "regenerate the whole graph" contract, which an LLM gets wrong on anything
non-trivial. Ops apply in order onto a working copy, so add_node → connect in one
batch just works (the new node is visible to later ops).
"""

from __future__ import annotations

import copy
from typing import Any

from app.domain.workflows import NODE_TYPES, WorkflowDomainError

GRAPH_OP_KINDS = (
    "add_node",
    "connect",
    "connect_data",
    "set_node_config",
    "set_node_name",
    "remove_node",
    "remove_edge",
)


def _require_node(by_id: dict[str, dict], node_id: str) -> dict:
    node = by_id.get(node_id)
    if node is None:
        raise WorkflowDomainError(f"节点不存在: {node_id or '(空)'}")
    return node


def apply_graph_ops(graph: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Apply granular ops onto a copy of `graph`; return the new graph (unvalidated).

    Raises WorkflowDomainError on a malformed op (unknown node type, missing node, etc.).
    Callers should run validate_graph on the result before persisting.
    """
    g = copy.deepcopy(graph)
    nodes: list[dict] = g.setdefault("nodes", [])
    edges: list[dict] = g.setdefault("edges", [])
    by_id: dict[str, dict] = {str(n.get("id")): n for n in nodes}

    def gen_node_id(node_type: str) -> str:
        base = node_type or "node"
        i = 1
        while f"{base}_{i}" in by_id:
            i += 1
        return f"{base}_{i}"

    def next_position() -> dict:
        max_x = max((int((n.get("position") or {}).get("x", 0)) for n in nodes), default=0)
        return {"x": max_x + 240, "y": 160}

    for op in operations:
        kind = str(op.get("kind", ""))
        if kind == "add_node":
            node_type = str(op.get("type", ""))
            if node_type not in NODE_TYPES:
                raise WorkflowDomainError(f"未知节点类型: {node_type or '(空)'}")
            if node_type == "start":
                raise WorkflowDomainError("已有开始节点,不能再添加 start 节点")
            node_id = str(op.get("node_id") or "").strip() or gen_node_id(node_type)
            if node_id in by_id:
                raise WorkflowDomainError(f"节点 id 已存在: {node_id}")
            node = {
                "id": node_id,
                "type": node_type,
                "name": str(op.get("name") or NODE_TYPES[node_type]["label"]),
                "position": op.get("position") or next_position(),
                "config": dict(op.get("config") or {}),
            }
            nodes.append(node)
            by_id[node_id] = node
        elif kind == "connect":
            source = str(op.get("source", ""))
            target = str(op.get("target", ""))
            _require_node(by_id, source)
            _require_node(by_id, target)
            handle = op.get("source_handle")
            edge_id = f"e-{source}{('-' + str(handle)) if handle else ''}-{target}"
            if not any(str(e.get("id")) == edge_id for e in edges):
                edge: dict[str, Any] = {"id": edge_id, "source": source, "target": target}
                if handle:
                    edge["source_handle"] = handle
                edges.append(edge)
        elif kind == "connect_data":
            source = str(op.get("source", ""))
            target = str(op.get("target", ""))
            output = str(op.get("source_output", ""))
            target_input = str(op.get("target_input", ""))
            _require_node(by_id, source)
            target_node = _require_node(by_id, target)
            if not output or not target_input:
                raise WorkflowDomainError("connect_data 需要 source_output 和 target_input")
            # One data edge per (target, input): drop any existing binding for that input first.
            edges[:] = [
                e
                for e in edges
                if not (str(e.get("kind")) == "data" and str(e.get("target")) == target and str(e.get("target_input")) == target_input)
            ]
            edges.append(
                {
                    "id": f"d-{source}-{output}-{target}-{target_input}",
                    "source": source,
                    "target": target,
                    "kind": "data",
                    "source_output": output,
                    "target_input": target_input,
                }
            )
            inputs = target_node.setdefault("inputs", [])
            if target_input not in inputs:
                inputs.append(target_input)
            target_node.setdefault("config", {}).setdefault(target_input, "")
        elif kind == "set_node_config":
            node = _require_node(by_id, str(op.get("node_id", "")))
            node.setdefault("config", {}).update(dict(op.get("config") or {}))
        elif kind == "set_node_name":
            node = _require_node(by_id, str(op.get("node_id", "")))
            node["name"] = str(op.get("name", ""))
        elif kind == "remove_node":
            node_id = str(op.get("node_id", ""))
            if by_id.get(node_id, {}).get("type") == "start":
                raise WorkflowDomainError("不能删除开始节点")
            nodes[:] = [n for n in nodes if str(n.get("id")) != node_id]
            edges[:] = [e for e in edges if str(e.get("source")) != node_id and str(e.get("target")) != node_id]
            by_id.pop(node_id, None)
        elif kind == "remove_edge":
            edge_id = str(op.get("edge_id", ""))
            edges[:] = [e for e in edges if str(e.get("id")) != edge_id]
        else:
            raise WorkflowDomainError(f"不支持的图操作: {kind or '(空)'}")

    return g
