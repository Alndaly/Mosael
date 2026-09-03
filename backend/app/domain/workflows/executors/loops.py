"""循环节点与循环体子图执行。

run_subgraph 与主引擎共享同一套输入绑定(binding.py)与执行器注册表,少了
job/TaskEvent/并行机制——循环体是同步的、每迭代一个子作用域。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Workflow
from app.domain.workflows import WorkflowDomainError, interpolate, validate_body_graph
from app.domain.workflows.executors import register
from app.domain.workflows.executors.common import truthy

LOOP_WHILE_HARD_CAP = 1000
# foreach had no cap at all, while `while` was clamped — an asymmetry that mattered because
# `items` can come from a code, http_request or json_extract node, i.e. from remote data. Every
# iteration also accumulates its result (the whole sub-context when `output` is blank), so an
# unbounded list is a memory problem before it is a time problem, and nested loops multiply.
LOOP_FOREACH_HARD_CAP = 1000


def run_subgraph(body: dict[str, Any], base_context: dict[str, Any], *, workflow_id: str) -> dict[str, Any]:
    """跑一个循环体子图并返回其上下文。**与主引擎同一套内核**(execute_graph):并行调度、数据边
    绑定、{{var}} 插值、条件分支语义完全一致——不再是阉割版。`base_context` 播种循环作用域
    (如 {"loop": {"item": ..., "index": ...}}),子图节点用 {{loop.item}}/{{loop.index}} 与
    {{node_id.output}} 互相引用;无入边的根即入口(entry_is_root)。
    """
    errors = validate_body_graph(body)
    if errors:
        raise WorkflowDomainError("；".join(errors))
    from app.domain.workflows.engine import execute_graph  # 惰性:避开 engine↔executors 循环导入

    context, _cancelled = execute_graph(
        body, wf_id=workflow_id, initial_context=base_context, entry_is_root=True
    )
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
    inputs = config.get("inputs")
    shared_inputs = dict(inputs) if isinstance(inputs, dict) else {}
    if len(items) > LOOP_FOREACH_HARD_CAP:
        raise WorkflowDomainError(
            f"循环·遍历的 items 有 {len(items)} 项,超过上限 {LOOP_FOREACH_HARD_CAP};请先筛选或分批"
        )
    results: list[Any] = []
    for index, item in enumerate(items):
        ctx = run_subgraph(
            body,
            {"loop": {"item": item, "index": index}, "input": shared_inputs},
            workflow_id=workflow.id,
        )
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
