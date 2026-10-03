"""循环节点与循环体子图执行。

每次迭代经 common.run_body 跑一遍体(与主引擎同一套内核),一个子作用域;
遍历循环可以让几次迭代同时跑(`concurrency`),结果仍按原顺序交出。
"""

from __future__ import annotations

import contextvars
import json
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy.orm import Session

from app.domain.workflows import WorkflowDomainError, interpolate
from app.domain.workflows.executors.registry import RunScope, register
from app.domain.workflows.executors.common import at_least, run_body, truthy, whole_number
from app.domain.workflows.run_scope import halted, shared_halt

#: `item` 的"没给"哨兵。loop_while 没有当前项,而 None / "" 都是合法的迭代项,不能拿来当哨兵。
_NO_ITEM = object()

LOOP_WHILE_HARD_CAP = 1000
#: 条件循环没填最多几轮时跑几轮。
LOOP_WHILE_DEFAULT_ITERATIONS = 50
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

    **被叫停不是这一项失败了**:用户取消、同一张图里别的节点失败时,这一项抛的是 wfErr_cancelled ——
    原样交出去。此前它也被包成「第 3/20 次迭代失败:已取消」,读起来像第 3 项自己出了错。只认**这一轮真在停**
    时的取消:这一轮没在停、这一项里的子任务自己被取消了(供应商那边撤了单),那是这一项失败。
    """
    try:
        yield
    except WorkflowDomainError as exc:
        if exc.key == "wfErr_cancelled" and halted():
            raise
        where = f"第 {index + 1}/{total} 次迭代"
        if item is not _NO_ITEM:
            where += f"({_brief(item)})"
        raise WorkflowDomainError("wfErr_loopIterationFailed", params={"where": where, "reason": exc}) from exc
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
        items = _items_from_text(items)
    if not isinstance(items, list):
        raise WorkflowDomainError("wfErr_loopItems")
    body = config.get("body") or {"nodes": [], "edges": []}
    output_tpl = config.get("output", "")
    inputs = config.get("inputs")
    shared_inputs = dict(inputs) if isinstance(inputs, dict) else {}
    #: 最多取前几项。模板里接开始参数(`{{start.max_shots}}`):「要几组」此前只写进提示词,模型多给几组就多付几次钱。
    #: 留空不限;多出来的那几项不跑,条数交在 dropped。
    limit = whole_number(config, "max_items", node_type="loop_foreach")
    dropped = 0
    if limit is not None:
        limit = at_least(limit, 1, key="max_items", node_type="loop_foreach")
        dropped = max(0, len(items) - limit)
        items = items[:limit]
    if len(items) > LOOP_FOREACH_HARD_CAP:
        raise WorkflowDomainError(
            "wfErr_loopTooMany", params={"count": len(items), "cap": LOOP_FOREACH_HARD_CAP}
        )
    concurrency = _concurrency(config)
    #: 一项失败怎么办:stop(默认)整条循环失败;skip 记下这一项、接着跑别的 —— 各项彼此独立时(每条切片、
    #: 每组上身图、每种面料效果图)一项失败不该让已经付了钱的其余几项白做。跳过的那几项不进 results。
    skip = str(config.get("on_item_error") or "stop").strip().lower() == "skip"
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

    failures: list[tuple[int, BaseException]] = []
    if concurrency == 1 or total <= 1:
        results = []
        for index, item in enumerate(items):
            _stop_if_halted()
            try:
                results.append(iterate(index, item))
            except Exception as exc:  # noqa: BLE001 — 只有 skip 时才记下继续,其余原样抛出
                if not skip or halted():
                    raise
                failures.append((index, exc))
    else:
        results, failures = _iterate_concurrently(iterate, items, concurrency, skip=skip)
    return {
        "results": results,
        "count": len(results),
        "dropped": dropped,
        #: 跳过的那几项是第几项(从 1 数),和给人看的一句话(一项一行;没有就是空串,可以直接拼进通知)。
        "failed": [index + 1 for index, _ in failures],
        "failure_note": "\n".join(_skipped_line(index, exc) for index, exc in failures),
    }


def _skipped_line(index: int, exc: BaseException) -> str:
    from app.core.i18n import tr

    reason = getattr(exc, "params", {}).get("reason") or exc
    return tr("wfLoop_itemSkipped", index=index + 1, reason=str(reason))


def _items_from_text(text: str) -> list[Any]:
    """一段文字当遍历的列表:**先当 JSON 数组**(接 LLM 的 text 输出),不是 JSON 再按行拆(手填)。

    和 common.text_lines 同一个顺序。此前只按行拆:LLM 交出一段排好版的 JSON 数组,被拆成
    `[`、`  "第一镜",`、`]` 这样的几项,每一项都去跑了一遍循环体。一个 JSON 对象不是列表,报错。
    """
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        raise WorkflowDomainError("wfErr_loopItems")
    return [line.strip() for line in text.splitlines() if line.strip()]


def _concurrency(config: dict[str, Any]) -> int:
    """同时跑几项。和别的整数格同一个判法(common.whole_number):`"2.0"` 是 2,`"2.5"` 报「必须是整数」——
    此前 `int(float(…))` 把 2.5 悄悄截成 2。"""
    value = whole_number(config, "concurrency", node_type="loop_foreach", default=1)
    return max(1, min(value, LOOP_FOREACH_MAX_CONCURRENCY))


def _stop_if_halted() -> None:
    """这一轮在停(同一张图里别的节点失败了、外层被取消了),下一项就不开始。

    此前循环只认**自己**的失败:兄弟节点 0.3 秒就失败了,整条工作流已经判了失败,循环照样把
    20 项一项一项跑完、一项一项计费。停的信号由引擎立(见 workflows.run_scope)。
    """
    if halted():
        raise WorkflowDomainError("wfErr_cancelled")


class _NotStarted(Exception):
    """前面已经有一项失败(或这一轮在停),这一项就不开始了。"""


class _Stopped(Exception):
    """这一项开始了,跑到一半这一轮在停(别的项失败了、外层被叫停)被叫停 —— 不是自己失败的。"""


def _stopped(exc: BaseException | None) -> bool:
    """这一项是被叫停的(没开始,或跑到一半这一轮在停),不是自己失败的。"""
    return isinstance(exc, (_NotStarted, _Stopped))


def _iterate_concurrently(
    iterate, items: list[Any], concurrency: int, *, skip: bool = False
) -> tuple[list[Any], list[tuple[int, BaseException]]]:
    """几项同时跑,结果**按原顺序**交出(连同 `skip` 时跳过的那几项)。

    默认 fail-fast:一项失败,还没开始的不再开始;已经在跑的,**下一个节点不再开始**、正在等的
    子任务由等的一方取消(见 common.wait_until)。正在跑的那一个节点本身跑完 —— 半截的供应商调用
    中途扔下只会留下孤儿任务。`skip` 时一项失败不拦别的项,失败的那几项记下交回去;这一轮在停(取消、
    别的节点失败)时照旧不再开始。

    「停」是**同一个**信号,压进每一项自己那一层图(见 workflows.run_scope.shared_halt)。此前它只在
    这一层,各项的图看不见:一项失败之后,别的在跑的项照样一个节点一个节点往下跑,付费节点照开。

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
        with shared_halt(stop):
            if halted():
                raise _NotStarted()
            try:
                return iterate(index, item)
            except BaseException as exc:
                #: 这一轮真在停(别的项立了信号、外层被叫停)时的取消,是被叫停的,不是这一项失败了 —— 也不去立信号。
                if isinstance(exc, WorkflowDomainError) and exc.key == "wfErr_cancelled" and halted():
                    raise _Stopped() from exc
                # 自己失败了才立停的信号(skip 时不立:一项失败不拦别的项)。
                if not skip:
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
        if future.exception() is not None and not _stopped(future.exception())
    )
    skipped = sum(1 for future in futures if _stopped(future.exception()))
    if failures and not (skip and not skipped and not halted()):
        raise _all_failures(failures, total=len(items), skipped=skipped)
    if skipped:
        # 没有一项失败,却有被叫停的:是这一轮在停。不能交出一份缺了几项的结果。
        raise WorkflowDomainError("wfErr_cancelled")
    failed = {index for index, _ in failures}
    for future, index in futures.items():
        if index not in failed:
            results[index] = future.result()
    return [one for index, one in enumerate(results) if index not in failed], failures


def _all_failures(failures: list[tuple[int, BaseException]], *, total: int, skipped: int) -> BaseException:
    """把几项失败合成一个错误。只有一项失败、也没有跳过的时候,原样交出那一项的错误。"""
    first = failures[0][1]
    if len(failures) == 1 and not skipped:
        return first
    reason = getattr(first, "params", {}).get("reason") or str(first)
    return WorkflowDomainError(
        #: 没有被叫停的(各项都开始了、也都跑完了)就不提「另有 0 次因此停下」那半句。
        "wfErr_loopIterationsFailed" if skipped else "wfErr_loopIterationsFailedNoneStopped",
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
    # 按数解析,不合法就报错:此前填 0(`or 50`)或 "10.0"(int() 抛错被吞)都悄悄变成 50 轮。
    max_iter = whole_number(config, "max_iterations", node_type="loop_while", default=LOOP_WHILE_DEFAULT_ITERATIONS)
    max_iter = min(at_least(max_iter, 1, key="max_iterations", node_type="loop_while"), LOOP_WHILE_HARD_CAP)
    results: list[Any] = []
    index = 0
    # Do-while: the condition references body outputs, so it can only be evaluated after a run.
    while index < max_iter:
        _stop_if_halted()
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
