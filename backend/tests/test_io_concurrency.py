"""Independent I/O-bound work runs concurrently.

The rule these pin: work that spends its time WAITING (child processes, network) overlaps;
work that spends it in Python does not benefit and is left alone. Each test asserts real
overlap, not just a faster wall clock, so a regression to a sequential loop fails loudly."""

from __future__ import annotations

import threading
import time
from pathlib import Path

from app.domain.kb import graph as kb_graph
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


def test_kb_entity_extraction_overlaps_and_reads_the_db_once(monkeypatch) -> None:
    """Extraction is one LLM call per chunk. They must overlap — and the provider must be
    resolved a single time on the calling thread, not once per chunk inside a worker."""
    main_thread = threading.current_thread().name
    profile_reads: list[str] = []
    recorder = _OverlapRecorder(delay=0.05)

    def fake_profile(_db):
        profile_reads.append(threading.current_thread().name)
        return object()

    extracted: list[str] = []

    def fake_extract(_profile, text, call=None):
        recorder()
        extracted.append(text)
        return [{"name": text, "type": "X"}]

    monkeypatch.setattr(kb_graph, "_entity_profile", fake_profile)
    monkeypatch.setattr(kb_graph, "_extract_with", fake_extract)
    monkeypatch.setattr(kb_graph, "graph_tier_enabled", lambda: True)

    runs: list[tuple] = []

    class FakeSession:
        def run(self, *args, **kwargs):
            runs.append((threading.current_thread().name, args))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class FakeDriver:
        def session(self):
            return FakeSession()

    monkeypatch.setattr(kb_graph, "_get_driver", lambda: FakeDriver())

    chunks = [(f"c{i}", f"text {i}") for i in range(8)]
    kb_graph.upsert_document_graph(
        None, workspace_id="ws", document_id="doc", title="T", chunks=chunks
    )

    assert recorder.peak > 1, "chunks were extracted one after another"
    assert sorted(extracted) == sorted(t for _, t in chunks)
    assert len(profile_reads) == 1, f"provider resolved {len(profile_reads)} times, expected once"
    assert profile_reads[0] == main_thread, "provider was resolved from a worker thread"
    # Graph writes must stay on the calling thread — a neo4j Session is not thread-safe.
    assert {name for name, _ in runs} == {main_thread}
