"""Batch translation runs its round-trips concurrently.

A subtitle track is N independent network calls. Doing them one after another made translating
a 21-cue track take N × latency; these tests pin that they now overlap, that order and empty
cues survive, and that the DB is not touched from a worker thread."""

from __future__ import annotations

import threading
import time

import pytest

from app.domain import translate as tr


def test_batch_overlaps_instead_of_running_one_after_another(monkeypatch) -> None:
    delay = 0.1
    in_flight = 0
    peak = 0
    lock = threading.Lock()

    def fake_google(text, target, source="auto", client=None):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(delay)
        with lock:
            in_flight -= 1
        return f"[{target}] {text}"

    monkeypatch.setattr(tr, "google_translate", fake_google)

    texts = [f"cue {i}" for i in range(16)]
    started = time.perf_counter()
    out = tr.translate_many(None, texts, "en")
    elapsed = time.perf_counter() - started

    assert out == [f"[en] cue {i}" for i in range(16)], "order must survive the pool"
    assert peak > 1, "calls never overlapped — the batch is still sequential"
    # Sequential would be 16 × 0.1s = 1.6s. With the pool capped at 8 it is ~2 waves.
    assert elapsed < 16 * delay * 0.6, f"took {elapsed:.2f}s, barely better than sequential"


def test_concurrency_is_bounded(monkeypatch) -> None:
    in_flight = 0
    peak = 0
    lock = threading.Lock()

    def fake_google(text, target, source="auto", client=None):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        return text

    monkeypatch.setattr(tr, "google_translate", fake_google)
    tr.translate_many(None, [f"c{i}" for i in range(64)], "en")
    # Unbounded would open 64 sockets at once and get rate-limited by the free endpoint.
    assert peak <= tr._MAX_PARALLEL


def test_empty_cues_pass_through_without_a_network_call(monkeypatch) -> None:
    calls: list[str] = []

    def fake_google(text, target, source="auto", client=None):
        calls.append(text)
        return f"T:{text}"

    monkeypatch.setattr(tr, "google_translate", fake_google)
    out = tr.translate_many(None, ["hello", "", "   ", "world"], "en")
    assert out == ["T:hello", "", "", "T:world"]
    assert calls == ["hello", "world"], "blank cues must not cost a round-trip"


def test_one_failure_fails_the_batch(monkeypatch) -> None:
    def fake_google(text, target, source="auto", client=None):
        if text == "bad":
            raise tr.TranslateError("boom")
        return text

    monkeypatch.setattr(tr, "google_translate", fake_google)
    with pytest.raises(tr.TranslateError):
        tr.translate_many(None, ["ok", "bad", "ok2"], "en")


def test_ai_provider_is_read_once_before_the_pool_starts() -> None:
    """The DB read must happen on the calling thread. A Session belongs to one thread, so
    resolving the provider inside a worker would be a latent race."""
    reads: list[str] = []

    class FakeSession:
        def get(self, _model, profile_id):
            reads.append(threading.current_thread().name)
            return None

        def scalars(self, _stmt):
            reads.append(threading.current_thread().name)
            return self

        def first(self):
            return None

    with pytest.raises(tr.TranslateError):  # no enabled provider
        tr.translate_many(FakeSession(), ["a", "b", "c"], "en", engine="ai")
    assert reads, "provider was never resolved"
    assert all(name == threading.current_thread().name for name in reads), (
        "the DB was read from a worker thread"
    )
