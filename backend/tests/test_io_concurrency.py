"""Independent I/O-bound work runs concurrently.

The rule these pin: work that spends its time WAITING (child processes, network) overlaps;
work that spends it in Python does not benefit and is left alone. Each test asserts real
overlap, not just a faster wall clock, so a regression to a sequential loop fails loudly."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from app.media import probe as media_probe


class _OverlapRecorder:
    """Tracks how many calls are in flight at once."""

    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.peak = 0
        self._live = 0
        self._lock = threading.Lock()

    def __call__(self, *_args, **_kwargs):
        with self._lock:
            self._live += 1
            self.peak = max(self.peak, self._live)
        time.sleep(self.delay)
        with self._lock:
            self._live -= 1
        return True


def test_ffprobe_batch_overlaps_and_dedupes(monkeypatch) -> None:
    calls: list[Path] = []
    recorder = _OverlapRecorder()

    def fake(path):
        calls.append(path)
        return recorder(path)

    monkeypatch.setattr(media_probe, "probe_has_audio", fake)

    paths = [Path(f"/tmp/v{i}.mp4") for i in range(8)]
    # The same source used by several clips must only be probed once.
    result = media_probe.probe_has_audio_many(paths + paths[:3])

    assert set(result) == set(paths)
    assert len(calls) == 8, f"expected 8 probes after dedupe, got {len(calls)}"
    assert recorder.peak > 1, "probes ran one after another"


def test_ffprobe_batch_is_bounded(monkeypatch) -> None:
    recorder = _OverlapRecorder(delay=0.03)
    monkeypatch.setattr(media_probe, "probe_has_audio", recorder)
    media_probe.probe_has_audio_many([Path(f"/tmp/v{i}.mp4") for i in range(40)])
    assert recorder.peak <= media_probe._MAX_PARALLEL_PROBES
