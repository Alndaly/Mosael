"""A chatty or wedged agent child must not be able to hang the turn forever.

Both adapters gave the child stderr=PIPE and then read that pipe only after the stdout loop
ended. A child that logs more than one pipe buffer blocks writing stderr, stops producing
stdout, and we block reading it — a deadlock the configured timeout could not break, because
that timeout was an argument to process.wait(), which sits after the loop.

The visible damage was not the hang itself: the session stayed marked running, so every later
message in that chat was refused with "a turn is already in flight", with no error shown.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from app.core.child_process import ChildProcess


def _child(script: str) -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def test_a_child_that_floods_stderr_still_completes() -> None:
    """400KB of stderr — six times the pipe buffer — must not stall stdout."""
    script = (
        "import sys\n"
        "sys.stderr.write('x' * 400_000)\n"
        "sys.stderr.flush()\n"
        "print('{\"type\": \"turn_done\"}')\n"
    )
    started = time.perf_counter()
    child = ChildProcess(_child(script), timeout=20)
    lines = list(child.lines())
    child.finish()

    assert time.perf_counter() - started < 15, "stdout was blocked behind an undrained stderr"
    assert lines == ['{"type": "turn_done"}']
    assert child.timed_out is False


def test_stderr_is_reported_back_and_bounded() -> None:
    script = "import sys; sys.stderr.write('boom\\n' * 5000); print('done')"
    child = ChildProcess(_child(script), timeout=20)
    list(child.lines())
    tail = child.finish()

    assert "boom" in tail
    # Bounded — a chatty child must not be able to grow this without limit.
    assert len(tail) < 100_000


def test_a_silent_hang_is_killed_and_reported() -> None:
    """The deadline has to have teeth: nothing on stdout, nothing on stderr, never exits."""
    child = ChildProcess(_child("import time; time.sleep(300)"), timeout=1.0)
    started = time.perf_counter()
    lines = list(child.lines())  # returns once the kill closes stdout
    child.finish()

    assert time.perf_counter() - started < 20, "the watchdog never fired"
    assert lines == []
    assert child.timed_out is True, "the caller needs this to say WHY the turn produced nothing"


def test_a_prompt_child_is_not_killed() -> None:
    child = ChildProcess(_child("print('hello')"), timeout=30)
    lines = list(child.lines())
    child.finish()
    assert lines == ["hello"]
    assert child.timed_out is False


@pytest.mark.parametrize("payload", ["", "   ", "\n\n"])
def test_blank_stdout_lines_are_skipped(payload) -> None:
    child = ChildProcess(_child(f"print({payload!r}); print('real')"), timeout=20)
    assert list(child.lines()) == ["real"]
    child.finish()


# ---------------------------------------------------------------------------
# 另一条通往同一个症状的路:协议行读到了,子进程却还赖着不走
# ---------------------------------------------------------------------------

#: 真实形状:`_run_pi` 读到 `turn_done` 就 `break`(adapters.py:425 那段注释讲了为什么 ——
#: stdin 整轮不关,sidecar 的 readline 循环不会自己结束)。所以调 `finish()` 时子进程**还活着、
#: stdout 还开着**。第一版测试让子进程自己 close 掉 stdout 再睡,那是个 EOF 场景 ——
#: `lines()` 直接等满了 300 秒,`finish()` 反而什么都没赶上。断言要照着东西真正在的地方查。
_LINGERS = "import time; print('done', flush=True); time.sleep(300)"


def _read_one(child: ChildProcess) -> str:
    for line in child.lines():
        return line  # ← 拿到协议行就停,不等进程退出
    return ""


def test_收尾不会被一个赖着不走的子进程无限期挂住() -> None:
    """`finish()` 必须自己有时限,否则「把会话拨回 idle」那段永远执行不到。

    现场是 pi sidecar:用户按「停止」,stdin 关了、`main()` 返回了,但 Node 要等事件循环空了
    才退,而后台子智能体还挂着在飞的 HTTP 请求。症状和本文件开头记的那次**一模一样** ——
    会话永远标记为 running,之后每条消息都被拒绝且界面上不报错。

    原先 `finish()` 做的第一件事是 `self._killer.cancel()`,也就是**先拔掉那颗牙再无限期等**。
    这条测试钉住的就是那个顺序。
    """
    child = ChildProcess(_child(_LINGERS))
    assert _read_one(child) == "done"

    started = time.monotonic()
    child.finish(reap_timeout=1.0)
    elapsed = time.monotonic() - started

    assert elapsed < 10, f"finish() 等了 {elapsed:.1f} 秒 —— 它没有自己的时限,会把会话永久挂住"
    assert child.killed, "子进程还活着:finish() 返回了却没把它收掉"
    assert not child.timed_out, "这一轮是出了结果的,不该被报成「运行超过 N 秒未返回」"


def test_收尾期间看门狗还活着() -> None:
    """看门狗要留到 `wait()` 真的返回之后再撤 —— 它在收尾期间开火正是它存在的理由。"""
    child = ChildProcess(_child(_LINGERS), timeout=1.0)
    assert _read_one(child) == "done"

    started = time.monotonic()
    child.finish(reap_timeout=30.0)  # 远大于看门狗:**该由看门狗结束它**
    elapsed = time.monotonic() - started

    assert elapsed < 10, f"看门狗在 finish() 里被提前撤掉了(等了 {elapsed:.1f} 秒)"
    assert child.timed_out, "这次是真超时,调用方要能认出来"
