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

from app.audio.tts_providers import (
    REMOTE_PARALLEL,
    OpenAITTS,
    SpeechRequest,
    TTSError,
    synthesize_many,
)


class _Recorder:
    """A provider that records how many synthesise calls overlapped."""

    id = "test"
    label = "Test"

    def __init__(self, parallel_safe: bool, delay: float = 0.05, fail_on: set[int] | None = None):
        self.parallel_safe = parallel_safe
        self.peak = 0
        self._live = 0
        self._lock = threading.Lock()
        self._delay = delay
        self._fail_on = fail_on or set()
        self.seen: list[str] = []

    def synthesize(self, request: SpeechRequest, out_path: Path) -> None:
        with self._lock:
            self._live += 1
            self.peak = max(self.peak, self._live)
            index = len(self.seen)
            self.seen.append(request.text)
        time.sleep(self._delay)
        with self._lock:
            self._live -= 1
        if index in self._fail_on:
            raise TTSError(f"cue {index} failed")
        out_path.write_bytes(b"RIFF")


def _batch(n: int, tmp_path: Path):
    return (
        [SpeechRequest(text=f"line {i}") for i in range(n)],
        [tmp_path / f"{i}.wav" for i in range(n)],
    )


def test_a_remote_engine_synthesises_cues_concurrently(tmp_path: Path) -> None:
    provider = _Recorder(parallel_safe=True)
    requests, paths = _batch(12, tmp_path)

    started = time.perf_counter()
    errors = synthesize_many(provider, requests, paths)
    elapsed = time.perf_counter() - started

    assert errors == [None] * 12
    assert provider.peak > 1, "a remote engine ran one cue at a time"
    assert elapsed < 12 * 0.05 * 0.7, "no faster than serial"


def test_a_local_engine_is_kept_to_one_at_a_time(tmp_path: Path) -> None:
    """Two local model instances at once is slower, not faster, and can exhaust VRAM."""
    provider = _Recorder(parallel_safe=False)
    requests, paths = _batch(6, tmp_path)

    assert synthesize_many(provider, requests, paths) == [None] * 6
    assert provider.peak == 1


def test_remote_concurrency_is_bounded(tmp_path: Path) -> None:
    provider = _Recorder(parallel_safe=True, delay=0.03)
    requests, paths = _batch(40, tmp_path)
    synthesize_many(provider, requests, paths)
    assert provider.peak <= REMOTE_PARALLEL


def test_one_failed_cue_does_not_lose_the_rest(tmp_path: Path) -> None:
    """A hundred-line dub should not be discarded because line 3 hit a rate limit — and the
    caller needs to know WHICH lines to retry."""
    provider = _Recorder(parallel_safe=True, fail_on={3})
    requests, paths = _batch(8, tmp_path)

    errors = synthesize_many(provider, requests, paths)

    assert sum(1 for e in errors if e is not None) == 1
    assert isinstance(errors[3], TTSError)
    assert all(paths[i].exists() for i in range(8) if i != 3)


def test_order_is_preserved(tmp_path: Path) -> None:
    provider = _Recorder(parallel_safe=True)
    requests, paths = _batch(10, tmp_path)
    synthesize_many(provider, requests, paths)
    for i, path in enumerate(paths):
        assert path.exists(), f"cue {i} produced no file"


def test_mismatched_lengths_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        synthesize_many(_Recorder(True), [SpeechRequest(text="a")], [])


class TestOpenAI:
    def test_a_missing_key_fails_before_any_request(self) -> None:
        with pytest.raises(TTSError, match="API Key"):
            OpenAITTS(api_key="")

    def test_speed_is_passed_to_the_engine(self, monkeypatch, tmp_path: Path) -> None:
        """Dubbing needs the model to pace itself; stretching the waveform afterwards sounds
        worse than asking for a faster read."""
        captured: dict = {}

        class FakeResponse:
            content = b"RIFF"

            def raise_for_status(self):
                return None

        def fake_post(url, **kwargs):
            captured.update(kwargs["json"])
            return FakeResponse()

        monkeypatch.setattr("app.audio.tts_providers.httpx.post", fake_post)
        OpenAITTS(api_key="k").synthesize(SpeechRequest(text="hi", speed=1.25), tmp_path / "o.wav")
        assert captured["speed"] == pytest.approx(1.25)

    def test_natural_pace_sends_no_speed_at_all(self, monkeypatch, tmp_path: Path) -> None:
        captured: dict = {}

        class FakeResponse:
            content = b"RIFF"

            def raise_for_status(self):
                return None

        monkeypatch.setattr(
            "app.audio.tts_providers.httpx.post",
            lambda url, **kw: (captured.update(kw["json"]), FakeResponse())[1],
        )
        OpenAITTS(api_key="k").synthesize(SpeechRequest(text="hi"), tmp_path / "o.wav")
        assert "speed" not in captured
