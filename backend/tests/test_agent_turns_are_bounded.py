"""智能体回合有准入上限:超过上限的排队,不再无限起线程和 sidecar。"""

from __future__ import annotations

import threading
import time

from app.domain.agent.turn_scheduler import TurnScheduler


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not reached")


def test_only_max_active_turns_run_at_once() -> None:
    scheduler = TurnScheduler(max_active=2)
    release = threading.Event()
    started: list[str] = []

    def body(session_id: str) -> None:
        started.append(session_id)
        release.wait(2)

    for session_id in ("s1", "s2", "s3", "s4"):
        scheduler.submit(session_id, lambda sid=session_id: body(sid))

    _wait_until(lambda: len(started) == 2)
    assert started == ["s1", "s2"]
    assert not scheduler.idle()
    release.set()
    assert scheduler.wait_for_idle(2), "排队的两轮没有接着跑"


def test_cancel_removes_a_queued_turn_before_it_starts() -> None:
    scheduler = TurnScheduler(max_active=1)
    release = threading.Event()
    started: list[str] = []

    def body(session_id: str) -> None:
        started.append(session_id)
        release.wait(2)

    scheduler.submit("running", lambda: body("running"))
    _wait_until(lambda: started == ["running"])
    scheduler.submit("waiting", lambda: body("waiting"))
    assert scheduler.cancel("waiting") is True
    release.set()
    assert scheduler.wait_for_idle(2)
    assert started == ["running"], "被撤掉的排队回合仍然启动了"


def test_cancel_does_not_pretend_to_stop_an_already_started_turn() -> None:
    scheduler = TurnScheduler(max_active=1)
    release = threading.Event()

    def body() -> None:
        release.wait(2)

    scheduler.submit("s1", body)
    _wait_until(lambda: not scheduler.idle())
    assert scheduler.cancel("s1") is False
    release.set()
    assert scheduler.wait_for_idle(2)
