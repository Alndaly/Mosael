"""循环节点与循环体子图执行。

每次迭代经 common.run_body 跑一遍体(与主引擎同一套内核),一个子作用域;
遍历循环可以让几次迭代同时跑(`concurrency`),结果仍按原顺序交出。
"""

from __future__ import annotations

import contextvars
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy.orm import Session

from app.domain.workflows import WorkflowDomainError, interpolate
from app.domain.workflows.executors import RunScope, register
from app.domain.workflows.executors.common import run_body, truthy

#: `item` 的"没给"哨兵。loop_while 没有当前项,而 None / "" 都是合法的迭代项,不能拿来当哨兵。
_NO_ITEM = object()

LOOP_WHILE_HARD_CAP = 1000
# foreach had no cap at all, while `while` was clamped — an asymmetry that mattered because
# `items` can come from a code, http_request or json_extract node, i.e. from remote data. Every
# iteration also accumulates its result (the whole sub-context when `output` is blank), so an
# unbounded list is a memory problem before it is a time problem, and nested loops multiply.
LOOP_FOREACH_HARD_CAP = 1000
#: 遍历循环最多几次迭代同时跑。**不是越大越好**:循环体里多半是调供应商(按账号限流、按条计费)
#: 或本机重活(导出、合成),而循环会嵌套 —— 外层 4 × 内层 4 就是 16 路。
LOOP_FOREACH_MAX_CONCURRENCY = 4


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
        raise WorkflowDomainError("wfErr_loopIterationFailed", params={"where": where, "reason": exc}) from exc


def _brief(item: Any) -> str:
    """迭代项的一眼可认版本。素材项可能是整个 dict,原样拼进错误里会糊满一屏。"""
    text = item if isinstance(item, str) else repr(item)
    return text if len(text) <= 60 else text[:57] + "…"


@register("loop_foreach")
def loop_foreach(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    items = config.get("items")
    if isinstance(items, str):
        items = [line.strip() for line in items.splitlines() if line.strip()]
    if not isinstance(items, list):
        raise WorkflowDomainError("wfErr_loopItems")
    body = config.get("body") or {"nodes": [], "edges": []}
    output_tpl = config.get("output", "")
    inputs = config.get("inputs")
    shared_inputs = dict(inputs) if isinstance(inputs, dict) else {}
    if len(items) > LOOP_FOREACH_HARD_CAP:
        raise WorkflowDomainError(
            "wfErr_loopTooMany", params={"count": len(items), "cap": LOOP_FOREACH_HARD_CAP}
        )
    concurrency = _concurrency(config.get("concurrency"))
    total = len(items)

    def iterate(index: int, item: Any) -> Any:
        with _blame_iteration(index, total, item=item):
            ctx = run_body(
                "loop_foreach",
                body,
                {"loop": {"item": item, "index": index}, "input": shared_inputs},
                workflow_id=scope.id,
            )
        if output_tpl:
            return interpolate(output_tpl, ctx)
        # 不写 output 时交出这一次的全部产物,**连同这一项本身**(`loop.item` / `loop.index`)——
        # 下游再遍历这份结果时,常常还要用到当初那一项的数据。共享输入每项都一样,不重复带。
        return {nid: out for nid, out in ctx.items() if nid != "input"}

    if concurrency == 1 or total <= 1:
        results = [iterate(index, item) for index, item in enumerate(items)]
    else:
        results = _iterate_concurrently(iterate, items, concurrency)
    return {"results": results, "count": len(results)}


def _concurrency(raw: Any) -> int:
    try:
        value = int(float(raw)) if raw not in (None, "") else 1
    except (TypeError, ValueError):
        raise WorkflowDomainError("wfErr_concurrencyInteger") from None
    return max(1, min(value, LOOP_FOREACH_MAX_CONCURRENCY))


class _NotStarted(Exception):
    """前面已经有一项失败,这一项就不开始了。"""


def _iterate_concurrently(iterate, items: list[Any], concurrency: int) -> list[Any]:
    """几项同时跑,结果**按原顺序**交出。

    仍然 fail-fast:一项失败,还没开始的不再开始(已经在跑的跑完 —— 半截的供应商调用中途
    扔下只会留下孤儿任务)。

    **"不再开始"要由每一项自己在开头检查,不能靠事后 cancel。** 此前是 `wait(FIRST_EXCEPTION)`
    返回之后再逐个 `future.cancel()` —— 而失败那一项的线程一空出来,线程池立刻就把排队的下一项
    捡起来跑了,主线程的 cancel 永远晚一步。真机上付过账:三条视频同时失败后,第四条视频照样
    提交了出去,又扣了一次钱。所以停止信号在**失败那一刻、在同一个线程里**立起来,下一项开跑
    前先看它。

    失败**全部**报出来,不只报序号最小的那个:三项都失败时只说"第 1 项失败",用户会以为另外
    两项是好的 —— 而它们每一项都可能对应一笔已经花出去的钱。
    """
    results: list[Any] = [None] * len(items)
    stop = threading.Event()

    def guarded(index: int, item: Any) -> Any:
        if stop.is_set():
            raise _NotStarted()
        try:
            return iterate(index, item)
        except BaseException:
            stop.set()
            raise

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        # 线程池里的线程不继承 contextvar:每一项带着当前上下文进去(外层任务的归属、取消边界,
        # 与 engine.run_node 同一个做法)。
        futures = {
            pool.submit(contextvars.copy_context().run, guarded, index, item): index
            for index, item in enumerate(items)
        }
        wait(futures)
    failures = sorted(
        (index, future.exception())
        for future, index in futures.items()
        if future.exception() is not None and not isinstance(future.exception(), _NotStarted)
    )
    if failures:
        skipped = sum(1 for future in futures if isinstance(future.exception(), _NotStarted))
        raise _all_failures(failures, total=len(items), skipped=skipped)
    for future, index in futures.items():
        results[index] = future.result()
    return results


def _all_failures(failures: list[tuple[int, BaseException]], *, total: int, skipped: int) -> BaseException:
    """把几项失败合成一个错误。只有一项失败、也没有跳过的时候,原样交出那一项的错误。"""
    first = failures[0][1]
    if len(failures) == 1 and not skipped:
        return first
    reason = getattr(first, "params", {}).get("reason") or str(first)
    return WorkflowDomainError(
        "wfErr_loopIterationsFailed",
        params={
            "count": len(failures),
            "total": total,
            # 列表交给渲染去连:顿号还是逗号是读的人的语言说了算(见 core/i18n._resolve_params)。
            "which": [index + 1 for index, _ in failures],
            "skipped": skipped,
            "reason": reason,
        },
    )


@register("loop_while")
def loop_while(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
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
            ctx = run_body("loop_while", body, {"loop": {"index": index}}, workflow_id=scope.id)
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
