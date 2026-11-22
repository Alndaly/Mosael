"""智能体回合的准入器。

一轮对话会起一个 Node sidecar,并占住线程直到模型/网络/工具全部结束。任务总线有 16 个名额,
回合此前没有上限:多开对话、飞书群、回执同时来,就能拉起任意多个 sidecar。这里把「同时真在跑
几轮」收在一个小接口后面:超过 `max_active` 的回合排队,而不是再起线程。

**不是线程池**:每轮仍然一个线程,但活着的线程最多 `max_active` 个;排队项只是内存里的
`(session_id, body)`。`cancel` 只撤还没开始的那一轮 —— 已经开始的由 `abort_turn` 处理。
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable
from time import monotonic, sleep


class TurnScheduler:
    def __init__(self, max_active: int = 8) -> None:
        self.max_active = max_active
        self._lock = threading.Lock()
        self._queue: deque[tuple[str, Callable[[], None]]] = deque()
        self._active = 0
        self._running: set[str] = set()
        self._started: set[str] = set()
        self._cancelled: set[str] = set()

    def submit(self, session_id: str, body: Callable[[], None]) -> None:
        with self._lock:
            self._queue.append((session_id, body))
            admitted = self._admit_locked()
        self._start(admitted)

    def cancel(self, session_id: str) -> bool:
        """撤掉还没开始的那一轮。已经开始、或没有这一轮时返回 False。"""
        with self._lock:
            for index, (queued, _body) in enumerate(self._queue):
                if queued == session_id:
                    del self._queue[index]
                    return True
            if session_id in self._running and session_id not in self._started:
                self._cancelled.add(session_id)
                return True
            return False

    def idle(self) -> bool:
        with self._lock:
            return not self._active and not self._queue

    def wait_for_idle(self, timeout: float = 5.0) -> bool:
        deadline = monotonic() + timeout
        while monotonic() < deadline:
            if self.idle():
                return True
            sleep(0.01)
        return self.idle()

    def _admit_locked(self) -> list[tuple[str, Callable[[], None]]]:
        admitted: list[tuple[str, Callable[[], None]]] = []
        while self._active < self.max_active and self._queue:
            session_id, body = self._queue.popleft()
            self._active += 1
            self._running.add(session_id)
            admitted.append((session_id, body))
        return admitted

    def _start(self, admitted: list[tuple[str, Callable[[], None]]]) -> None:
        for session_id, body in admitted:
            threading.Thread(target=self._run, args=(session_id, body), daemon=True, name="agent-turn").start()

    def _run(self, session_id: str, body: Callable[[], None]) -> None:
        skip = False
        with self._lock:
            if session_id in self._cancelled:
                self._cancelled.discard(session_id)
                skip = True
            else:
                self._started.add(session_id)
        try:
            if not skip:
                body()
        finally:
            with self._lock:
                self._running.discard(session_id)
                self._started.discard(session_id)
                self._active -= 1
                admitted = self._admit_locked()
            self._start(admitted)


_scheduler = TurnScheduler()


def submit(session_id: str, body: Callable[[], None]) -> None:
    _scheduler.submit(session_id, body)


def cancel(session_id: str) -> bool:
    return _scheduler.cancel(session_id)


def idle() -> bool:
    return _scheduler.idle()


def wait_for_idle(timeout: float = 5.0) -> bool:
    return _scheduler.wait_for_idle(timeout)


def reset_for_tests(max_active: int = 8) -> None:
    global _scheduler
    _scheduler = TurnScheduler(max_active)
