"""循环节点与循环体子图执行。

run_subgraph 与主引擎共享同一套输入绑定(binding.py)与执行器注册表,少了
job/TaskEvent/并行机制——循环体是同步的、每迭代一个子作用域。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import Workflow
from app.domain.workflows import (
    WorkflowDomainError,
    interpolate,
    topo_order,
    validate_body_graph,
)
from app.domain.workflows.binding import apply_data_edges, interpolate_node_config
from app.domain.workflows.executors import get_executor, register
from app.domain.workflows.executors.common import truthy

LOOP_WHILE_HARD_CAP = 1000
# foreach had no cap at all, while `while` was clamped — an asymmetry that mattered because
# `items` can come from a code, http_request or json_extract node, i.e. from remote data. Every
# iteration also accumulates its result (the whole sub-context when `output` is blank), so an
# unbounded list is a memory problem before it is a time problem, and nested loops multiply.
LOOP_FOREACH_HARD_CAP = 1000


def run_subgraph(body: dict[str, Any], base_context: dict[str, Any], *, workflow_id: str) -> dict[str, Any]:
    """Run a nested loop-body sub-graph synchronously (topo order) and return its context.

    Reuses the same handlers, data-edge binding, {{var}} interpolation and condition-branch
    semantics as the main engine, minus the job/TaskEvent/parallelism machinery. `base_context`
    seeds the loop scope (e.g. {"loop": {"item": ..., "index": ...}}); body nodes reference it as
    {{loop.item}} / {{loop.index}} and each other as {{node_id.output}}.
    """
    errors = validate_body_graph(body)
    if errors:
        raise WorkflowDomainError("；".join(errors))
    nodes = list(body.get("nodes") or [])
    edges = list(body.get("edges") or [])
    nodes_by_id = {str(n["id"]): n for n in nodes}
    node_types = {nid: str(n.get("type")) for nid, n in nodes_by_id.items()}
    incoming: dict[str, list[dict[str, Any]]] = {nid: [] for nid in nodes_by_id}
    for edge in edges:
        source, target = str(edge.get("source")), str(edge.get("target"))
        if source in nodes_by_id and target in nodes_by_id:
            incoming[target].append(edge)

    context: dict[str, Any] = dict(base_context)
    executed: set[str] = set()

    def incoming_active(nid: str) -> bool:
        node_edges = incoming.get(nid, [])
        if not node_edges:
            return True  # a body root (no incoming) is an entry point → always runs
        for edge in node_edges:
            source = str(edge.get("source"))
            if source not in executed:
                continue
            if node_types.get(source) == "condition":
                wanted = str(edge.get("source_handle") or "true")
                if wanted != ("true" if context.get(source, {}).get("result") else "false"):
                    continue
            return True
        return False

    for node in topo_order(body):
        nid = str(node["id"])
        ntype = node_types[nid]
        if not incoming_active(nid):
            continue  # unreached branch — skip (Dify semantics)
        config = apply_data_edges(nid, dict(node.get("config") or {}), edges, context)
        config = interpolate_node_config(ntype, config, context)
        handler = get_executor(ntype)
        if handler is None:
            raise WorkflowDomainError(f"节点类型 {ntype} 没有执行器")
        with SessionLocal() as sub_db:
            wf = sub_db.get(Workflow, workflow_id)
            context[nid] = handler(sub_db, wf, config)
        executed.add(nid)
    return context


@register("loop_foreach")
def loop_foreach(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    items = config.get("items")
    if isinstance(items, str):
        items = [line.strip() for line in items.splitlines() if line.strip()]
    if not isinstance(items, list):
        raise WorkflowDomainError("循环·遍历的 items 必须是列表(或多行文本)")
    body = config.get("body") or {"nodes": [], "edges": []}
    output_tpl = config.get("output", "")
    if len(items) > LOOP_FOREACH_HARD_CAP:
        raise WorkflowDomainError(
            f"循环·遍历的 items 有 {len(items)} 项,超过上限 {LOOP_FOREACH_HARD_CAP};请先筛选或分批"
        )
    results: list[Any] = []
    for index, item in enumerate(items):
        ctx = run_subgraph(body, {"loop": {"item": item, "index": index}}, workflow_id=workflow.id)
        if output_tpl:
            results.append(interpolate(output_tpl, ctx))
        else:
            results.append({nid: out for nid, out in ctx.items() if nid != "loop"})
    return {"results": results, "count": len(results)}


@register("loop_while")
def loop_while(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    body = config.get("body") or {"nodes": [], "edges": []}
    condition_tpl = str(config.get("condition") or "")
    output_tpl = config.get("output", "")
    try:
        max_iter = int(config.get("max_iterations") or 50)
    except (TypeError, ValueError):
        max_iter = 50
    max_iter = max(1, min(max_iter, LOOP_WHILE_HARD_CAP))
    results: list[Any] = []
    index = 0
    # Do-while: the condition references body outputs, so it can only be evaluated after a run.
    while index < max_iter:
        ctx = run_subgraph(body, {"loop": {"index": index}}, workflow_id=workflow.id)
        if output_tpl:
            results.append(interpolate(output_tpl, ctx))
        else:
            results.append({nid: out for nid, out in ctx.items() if nid != "loop"})
        index += 1
        if not condition_tpl:
            break  # no condition → run exactly once
        if not truthy(interpolate(condition_tpl, ctx)):
            break
    return {"results": results, "count": len(results), "iterations": index}
