"""循环节点与循环体子图执行。

run_subgraph 与主引擎共享同一套输入绑定(binding.py)与执行器注册表,少了
job/TaskEvent/并行机制——循环体是同步的、每迭代一个子作用域。
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy.orm import Session

from app.db.models import Workflow
from app.domain.workflows import WorkflowDomainError, interpolate, validate_body_graph
from app.domain.workflows.executors import register
from app.domain.workflows.executors.common import truthy

#: `item` 的"没给"哨兵。loop_while 没有当前项,而 None / "" 都是合法的迭代项,不能拿来当哨兵。
_NO_ITEM = object()

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
    if _cancelled:
        raise WorkflowDomainError("已取消")
    return context


@contextmanager
def _blame_iteration(index: int, total: int, *, item: Any = _NO_ITEM) -> Iterator[None]:
    """循环体炸了的时候,把**是第几项**写进错误里。

    一项失败会带崩整条循环(fail-fast,见下面两个执行器)——那本身是设计:后续迭代往往依赖
    前面的产物,硬着头皮跑完只会把一个错误变成一串。但代价是用户只看到子图节点抛的那句原话,
    比如「代码执行出错:KeyError: 'url'」——**跑了 200 个素材,不知道是哪一个**,而这恰恰是
    唯一能让人动手去查的信息。

    只加定位,不改语义:异常照样往上抛,原异常挂在 __cause__ 上,栈也完整。
    """
    try:
        yield
    except Exception as exc:  # noqa: BLE001 — 只加定位再原样抛出,不吞任何一种失败
        where = f"第 {index + 1}/{total} 次迭代"
        if item is not _NO_ITEM:
            where += f"({_brief(item)})"
        raise WorkflowDomainError(f"{where}失败:{exc}") from exc


def _brief(item: Any) -> str:
    """迭代项的一眼可认版本。素材项可能是整个 dict,原样拼进错误里会糊满一屏。"""
    text = item if isinstance(item, str) else repr(item)
    return text if len(text) <= 60 else text[:57] + "…"


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
        with _blame_iteration(index, len(items), item=item):
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
        with _blame_iteration(index, max_iter):
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
