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
        raise WorkflowDomainError("wfErr_nodeMissing", params={"id": node_id or '""'})
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
                raise WorkflowDomainError("wfErr_unknownNodeType", params={"type": node_type or '""'})
            if node_type == "start" and any(str(node.get("type")) == "start" for node in nodes):
                raise WorkflowDomainError("wfErr_startExists")
            node_id = str(op.get("node_id") or "").strip() or ("start" if node_type == "start" and "start" not in by_id else gen_node_id(node_type))
            if node_id in by_id:
                raise WorkflowDomainError("wfErr_nodeIdExists", params={"id": node_id})
            node = {
                "id": node_id,
                "type": node_type,
                # **不写名字。** `NODE_TYPES[...]["label"]` 存的是 i18n key(目录里存 key、
                # 出口才翻,由 test_backend_i18n 那道棘轮强制),把它当人话写进去的话,
                # 画布上那个节点从此就叫 `wfNode_scene_render` —— 而且它**随图落库**,
                # 是写进用户数据的错,不只是显示错,改对翻译之后还得靠迁移救回来。
                #
                # 留空就够了:显示时没有 name 会回退到**翻译后**的 label(见界面那一侧),
                # 而那正是用户想看到的。
                "name": str(op.get("name") or ""),
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
                raise WorkflowDomainError("wfErr_connectDataNeedsPorts")
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
            nodes[:] = [n for n in nodes if str(n.get("id")) != node_id]
            edges[:] = [e for e in edges if str(e.get("source")) != node_id and str(e.get("target")) != node_id]
            by_id.pop(node_id, None)
        elif kind == "remove_edge":
            edge_id = str(op.get("edge_id", ""))
            edges[:] = [e for e in edges if str(e.get("id")) != edge_id]
        else:
            raise WorkflowDomainError("wfErr_unknownGraphOp", params={"kind": kind or '""'})

    return g
