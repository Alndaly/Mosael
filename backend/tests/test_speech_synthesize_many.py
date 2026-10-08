"""Batching speech synthesis has to respect what the engine can actually do at once.

A remote engine is an HTTP request, so cues can overlap; a local clone engine holds one model in
memory and running two at once makes both slower and risks exhausting VRAM. Dubbing a transcript
means synthesising every cue, so this is the difference between seconds and many minutes.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from app.ai.providers import (
    MAX_PARALLEL_SPEECH_REQUESTS,
    SpeechSynthesisRequest,
    SpeechSynthesisError,
    synthesize_many,
)


class _Recorder:
    """An Adapter that records how many synthesise calls overlapped."""

    engine_id = "test"
    label_key = "Test"

    def __init__(self, supports_parallel_synthesis: bool, delay: float = 0.05, fail_on: set[int] | None = None):
        self.supports_parallel_synthesis = supports_parallel_synthesis
        self.peak = 0
        self._live = 0
        self._lock = threading.Lock()
        self._delay = delay
        self._fail_on = fail_on or set()
        self.seen: list[str] = []

    def synthesize(self, request: SpeechSynthesisRequest, out_path: Path) -> None:
        with self._lock:
            self._live += 1
            self.peak = max(self.peak, self._live)
            index = len(self.seen)
            self.seen.append(request.text)
        time.sleep(self._delay)
        with self._lock:
            self._live -= 1
        if index in self._fail_on:
            raise SpeechSynthesisError(f"cue {index} failed")
        out_path.write_bytes(b"RIFF")


def _batch(n: int, tmp_path: Path):
    return (
        [SpeechSynthesisRequest(text=f"line {i}") for i in range(n)],
        [tmp_path / f"{i}.wav" for i in range(n)],
    )


class _FirstWaitsForSecond(_Recorder):
    """第 1 句一直等到第 2 句也开始了才往下走 —— 一句一句来的话,第 2 句永远开始不了,第 1 句等满就报错。

    此前用总耗时证明「并发了」(`< 12 × 0.05 × 0.7` 秒):机器一忙,线程排不上,并发的那一批也走不进这条线
    (CI 式满载下实测 0.70 秒)。会齐不看钟:并发时当场会齐,不并发时必然等不到。
    """

    def __init__(self) -> None:
        super().__init__(supports_parallel_synthesis=True)
        self._second_started = threading.Event()

    def synthesize(self, request: SpeechSynthesisRequest, out_path: Path) -> None:
        if request.text == "line 1":
            self._second_started.set()
        if request.text == "line 0" and not self._second_started.wait(30):
            raise SpeechSynthesisError("cue 1 never started while cue 0 was in flight")
        super().synthesize(request, out_path)


def test_a_remote_engine_synthesises_cues_concurrently(tmp_path: Path) -> None:
    adapter = _FirstWaitsForSecond()
    requests, paths = _batch(12, tmp_path)

    errors = synthesize_many(adapter, requests, paths)

    assert errors == [None] * 12, "第 1 句在飞的时候第 2 句没开始 —— 远端引擎被一句一句地跑了"
    assert adapter.peak > 1, "a remote engine ran one cue at a time"


def test_a_local_engine_is_kept_to_one_at_a_time(tmp_path: Path) -> None:
    """Two local model instances at once is slower, not faster, and can exhaust VRAM."""
    adapter = _Recorder(supports_parallel_synthesis=False)
    requests, paths = _batch(6, tmp_path)

    assert synthesize_many(adapter, requests, paths) == [None] * 6
    assert adapter.peak == 1


def test_remote_concurrency_is_bounded(tmp_path: Path) -> None:
    adapter = _Recorder(supports_parallel_synthesis=True, delay=0.03)
    requests, paths = _batch(40, tmp_path)
    synthesize_many(adapter, requests, paths)
    assert adapter.peak <= MAX_PARALLEL_SPEECH_REQUESTS


def test_one_failed_cue_does_not_lose_the_rest(tmp_path: Path) -> None:
    """A hundred-line dub should not be discarded because line 3 hit a rate limit — and the
    caller needs to know WHICH lines to retry."""
    adapter = _Recorder(supports_parallel_synthesis=True, fail_on={3})
    requests, paths = _batch(8, tmp_path)

    errors = synthesize_many(adapter, requests, paths)

    assert sum(1 for e in errors if e is not None) == 1
    assert isinstance(errors[3], SpeechSynthesisError)
    assert all(paths[i].exists() for i in range(8) if i != 3)


def test_order_is_preserved(tmp_path: Path) -> None:
    adapter = _Recorder(supports_parallel_synthesis=True)
    requests, paths = _batch(10, tmp_path)
    synthesize_many(adapter, requests, paths)
    for i, path in enumerate(paths):
        assert path.exists(), f"cue {i} produced no file"


def test_mismatched_lengths_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        synthesize_many(_Recorder(True), [SpeechSynthesisRequest(text="a")], [])
