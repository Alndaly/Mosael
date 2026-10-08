"""进程内任务有上限,且等子任务的父任务不会把名额占死(domain/jobs.JobRunner)。"""

from __future__ import annotations

import threading
import time

from app.domain.jobs import JobRunner


def _until(predicate, timeout: float = 30.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return predicate()


def test_no_more_than_the_limit_run_at_once() -> None:
    runner = JobRunner(2)
    release = threading.Event()
    running: list[str] = []
    peak = [0]
    lock = threading.Lock()

    def body(name: str):
        def run() -> None:
            with lock:
                running.append(name)
                peak[0] = max(peak[0], len(running))
            release.wait(5)
            with lock:
                running.remove(name)

        return run

    for index in range(6):
        runner.submit(f"j{index}", body(f"j{index}"))
    #: 放不放行是在 submit 里(锁内)当场定的:提交完就看得到谁进了、谁在排。此前是睡 0.05 秒再看「在跑的还是两个」——
    #: 机器一忙,多放进来的那个线程还没跑起来,断言照样成立。
    assert len(runner._queue) == 4, "名额满了,其余的排队"
    assert _until(lambda: len(running) == 2)
    release.set()
    assert _until(runner.idle)
    assert peak[0] == 2


def test_a_parent_waiting_on_its_child_gives_up_its_slot() -> None:
    """名额只有一个:父任务等子任务时不让出来,子任务就永远排不上 —— 死锁。"""
    runner = JobRunner(1)
    child_done = threading.Event()
    parent_done = threading.Event()

    def child() -> None:
        child_done.set()

    def parent() -> None:
        runner.submit("child", child)
        with runner.parked("parent"):
            assert child_done.wait(5), "子任务没排上:父任务占着唯一的名额"
        parent_done.set()

    runner.submit("parent", parent)
    assert parent_done.wait(5)
    assert _until(runner.idle)


def test_several_waiters_in_one_job_release_one_slot() -> None:
    """并行节点同属一个任务:几条线程同时在等,也只让出这个任务的那一个名额。"""
    runner = JobRunner(1)
    entered = threading.Barrier(3)
    go = threading.Event()

    def parent() -> None:
        def waiter() -> None:
            with runner.parked("p"):
                entered.wait(5)
                go.wait(5)

        threads = [threading.Thread(target=waiter) for _ in range(2)]
        for thread in threads:
            thread.start()
        entered.wait(5)
        assert runner._active == 0  # noqa: SLF001 —— 就是要看计数
        go.set()
        for thread in threads:
            thread.join(5)
        assert runner._active == 1  # noqa: SLF001

    runner.submit("p", parent)
    assert _until(runner.idle)


def test_waiting_outside_a_dispatched_job_changes_nothing() -> None:
    runner = JobRunner(1)
    with runner.parked(None), runner.parked("not-running"):
        assert runner._active == 0  # noqa: SLF001
    assert runner.idle()
