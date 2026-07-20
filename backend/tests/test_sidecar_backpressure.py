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

from app.ai.agent.adapters import _ChildProcess


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
    child = _ChildProcess(_child(script), timeout=20)
    lines = list(child.lines())
    child.finish()

    assert time.perf_counter() - started < 15, "stdout was blocked behind an undrained stderr"
    assert lines == ['{"type": "turn_done"}']
    assert child.timed_out is False


def test_stderr_is_reported_back_and_bounded() -> None:
    script = "import sys; sys.stderr.write('boom\\n' * 5000); print('done')"
    child = _ChildProcess(_child(script), timeout=20)
    list(child.lines())
    tail = child.finish()

    assert "boom" in tail
    # Bounded — a chatty child must not be able to grow this without limit.
    assert len(tail) < 100_000


def test_a_silent_hang_is_killed_and_reported() -> None:
    """The deadline has to have teeth: nothing on stdout, nothing on stderr, never exits."""
    child = _ChildProcess(_child("import time; time.sleep(300)"), timeout=1.0)
    started = time.perf_counter()
    lines = list(child.lines())  # returns once the kill closes stdout
    child.finish()

    assert time.perf_counter() - started < 20, "the watchdog never fired"
    assert lines == []
    assert child.timed_out is True, "the caller needs this to say WHY the turn produced nothing"


def test_a_prompt_child_is_not_killed() -> None:
    child = _ChildProcess(_child("print('hello')"), timeout=30)
    lines = list(child.lines())
    child.finish()
    assert lines == ["hello"]
    assert child.timed_out is False


@pytest.mark.parametrize("payload", ["", "   ", "\n\n"])
def test_blank_stdout_lines_are_skipped(payload) -> None:
    child = _ChildProcess(_child(f"print({payload!r}); print('real')"), timeout=20)
    assert list(child.lines()) == ["real"]
    child.finish()
