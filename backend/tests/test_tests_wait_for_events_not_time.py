"""棘轮:测试里「睡一下再看」「耗时 < N 秒」只减不增 —— 测试等事件、等条件,不等时间。

**为什么要有这一道。** 这类写法在开发机上永远是绿的,要等 CI 机器哪天忙了才随机红 —— 而红的常常是无辜的那条。
2026-10 前后一个月里陆续修了几十条(21ec11fa5、fea85b935、d72668939、23a9713a8,以及 tests-ci 那三批),每次都是
CI 红了才一条条改;同一个文件里的兄弟没顺手改,新写的测试照旧这么写,并行和负载一变又冒出来。写法规矩见
docs/CONVENTIONS.md「测试里怎么等」。

**数的是这两种**(只看 `backend/tests/test_*.py`):
- **裸睡**:`time.sleep(...)` / `asyncio.sleep(...)` 不在循环里。循环里的是轮询的间隔(`while not done: sleep(0.05)`),
  不算;`asyncio.sleep(0)` 只是让一下事件循环,也不算。替身里「睡 0.4 秒假装在干活」算 —— 它造出来的是一个窗口,
  测试得赶在窗口里做完(要「它还在跑」,让替身卡在 Event 上、测试放行)。
- **量挂钟的断言**:`assert time.monotonic() - started < N`、`assert elapsed < N` 这类,拿一段耗时和常数比。
  要证明「没等那件慢事」,就让那件事一直卡着、断言返回时它还卡着;实在要比,线画在对照值的一半。

存量冻在下面两张表里,按文件计数。**新加一处会红**;改掉一处也会红 —— 把表里的数字改小(或删掉那一行),表才不会慢慢
变成一张谁都能往里加的白名单。真有一处非得这么写(比如本身就在测超时、测「多快」),在表里加上,并在那一行写清为什么。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

RATCHET = True

TESTS = Path(__file__).resolve().parent

#: 不在循环里的 time.sleep / asyncio.sleep,按文件。**只减不增。**
SLEEPS: dict[str, int] = {
    "test_a_broken_pipe_does_not_wedge_the_pool.py": 1,
    "test_agent_queue_drain.py": 2,
    "test_auth.py": 1,
    "test_browser_queue_timeout.py": 1,
    "test_browser_sessions_share_nothing_they_should_not.py": 1,
    "test_cancelled_work_stops_and_stays_cancelled.py": 2,
    "test_feishu_connections_leave_no_pump.py": 1,
    "test_io_concurrency.py": 1,
    "test_jobs_log_their_duration.py": 1,
    "test_local_services.py": 7,
    "test_long_lived_threads_survive.py": 1,
    "test_long_videos_get_filmstrips_and_proxies.py": 1,
    "test_loop_concurrency_and_full_video_assembly.py": 2,
    "test_loops_stop_when_the_run_halts.py": 1,
    "test_model_nsfw_local.py": 1,
    "test_plugin_calls_belong_to_their_job.py": 1,
    "test_probe_generations.py": 1,
    "test_provider_auth.py": 2,
    "test_references_are_dependencies.py": 1,
    "test_speech_synthesize_many.py": 1,
    "test_translate_batch.py": 5,
    "test_worker_admission.py": 1,
}

#: 拿一段耗时和常数比的断言,按文件。**只减不增。**
CLOCK_ASSERTS: dict[str, int] = {
    "test_a_hung_worker_still_times_out.py": 1,
    "test_board_producers.py": 1,
    "test_browser_executor_lost.py": 1,
    "test_child_process_backpressure.py": 4,
    "test_comfyui_plugin_managed.py": 1,
    "test_local_service_supervisor.py": 1,
    "test_manim_plugin.py": 1,
    "test_pi_turn_lifecycle.py": 1,
    "test_plugin_calls_belong_to_their_job.py": 1,
    "test_plugin_generation_providers.py": 2,
    "test_plugin_kits_are_identical.py": 2,
    "test_plugin_process_tree_is_stopped.py": 1,
    "test_plugin_runtime.py": 1,
    "test_plugin_tools_stream_and_many_files.py": 1,
    "test_restart_settles_before_it_wakes_anyone.py": 1,
    "test_shutdown_does_not_wait_forever.py": 1,
    "test_the_stderr_drain_cannot_die.py": 1,
    "test_waveform_peaks_are_fast_and_unchanged.py": 1,
}

_SLEEP_OWNERS = {"time", "_time", "_t", "asyncio"}
_CLOCKS = {"monotonic", "perf_counter", "time"}
_DURATION_NAME = re.compile(r"elapsed|took|spent|duration")


def _is_sleep(node: ast.AST) -> bool:
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "sleep"):
        return False
    if not (isinstance(node.func.value, ast.Name) and node.func.value.id in _SLEEP_OWNERS):
        return False
    #: `await asyncio.sleep(0)`:让一下事件循环,不是在等时间
    return not (node.args and isinstance(node.args[0], ast.Constant) and node.args[0].value == 0)


def _bare_sleeps(tree: ast.AST) -> list[int]:
    """不在循环里的睡,交回行号。循环 = 这一处往上、同一个函数里有 for / while。"""
    found: list[int] = []

    def visit(node: ast.AST, in_loop: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                visit(child, False)
                continue
            if _is_sleep(child) and not in_loop:
                found.append(child.lineno)
            visit(child, in_loop or isinstance(child, (ast.For, ast.AsyncFor, ast.While)))

    visit(tree, False)
    return found


def _is_clock(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in _CLOCKS
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in _SLEEP_OWNERS
    )


def _is_duration(node: ast.AST) -> bool:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
        return _is_clock(node.left) or _is_clock(node.right)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _is_duration(node.left)
    return isinstance(node, ast.Name) and bool(_DURATION_NAME.search(node.id))


def _clock_asserts(tree: ast.AST) -> list[int]:
    found: list[int] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assert) and isinstance(node.test, ast.Compare)):
            continue
        compare = node.test
        if any(isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)) for op in compare.ops) and any(
            _is_duration(side) for side in [compare.left, *compare.comparators]
        ):
            found.append(node.lineno)
    return found


def _scan() -> dict[str, tuple[list[int], list[int]]]:
    out: dict[str, tuple[list[int], list[int]]] = {}
    for path in sorted(TESTS.glob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        out[path.name] = (_bare_sleeps(tree), _clock_asserts(tree))
    return out


def _drift(kind: str, table: dict[str, int], found: dict[str, list[int]]) -> list[str]:
    lines: list[str] = []
    for name in sorted(set(table) | {name for name, at in found.items() if at}):
        allowed, at = table.get(name, 0), found.get(name, [])
        if len(at) > allowed:
            lines.append(f"  {name}:{kind} {len(at)} 处(表里是 {allowed}),在第 {', '.join(map(str, at))} 行 —— 新加的改成等事件 / 等条件")
        elif len(at) < allowed:
            lines.append(f"  {name}:{kind}剩 {len(at)} 处,表里还写着 {allowed} —— 改好了就把表里的数字改小(只减不增)")
    return lines


def test_测试里的裸睡和量挂钟的断言只减不增() -> None:
    scanned = _scan()
    drift = _drift("裸睡", SLEEPS, {name: sleeps for name, (sleeps, _) in scanned.items()}) + _drift(
        "量挂钟的断言", CLOCK_ASSERTS, {name: asserts for name, (_, asserts) in scanned.items()}
    )
    assert not drift, "测试里「等时间」的写法和存量表对不上(docs/CONVENTIONS.md「测试里怎么等」):\n" + "\n".join(drift)


@pytest.mark.parametrize(
    ("source", "sleeps", "asserts"),
    [
        ("def test_x():\n    do()\n    time.sleep(0.3)\n    assert done()\n", 1, 0),
        ("def test_x():\n    while not done():\n        time.sleep(0.05)\n", 0, 0),
        ("def test_x():\n    def slow():\n        time.sleep(0.4)\n    run(slow)\n", 1, 0),
        ("async def test_x():\n    await asyncio.sleep(0)\n", 0, 0),
        ("def test_x():\n    started = time.monotonic()\n    go()\n    assert time.monotonic() - started < 1\n", 0, 1),
        ("def test_x():\n    elapsed = measure()\n    assert elapsed < 0.5, elapsed\n", 0, 1),
        ("def test_x():\n    assert len(rows) < 3\n", 0, 0),
    ],
    ids=["睡完再看", "轮询的间隔", "替身里睡", "让一下事件循环", "量挂钟", "量耗时变量", "不相干的比较"],
)
def test_数法本身(source: str, sleeps: int, asserts: int) -> None:
    """数法要认得出该数的、放过不该数的 —— 不然上面那条只是在数一个随便的数。"""
    tree = ast.parse(source)
    assert (len(_bare_sleeps(tree)), len(_clock_asserts(tree))) == (sleeps, asserts)
