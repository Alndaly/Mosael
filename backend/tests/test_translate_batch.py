"""批量翻译按引擎采用不同的流控。

AI 供应商有正式配额，可以有限并发；Google 免费端点会限制客户端标识、出口或突发请求，只能串行。这里
同时钉住顺序、空字幕占位，以及 DB 不进入工作线程。"""

from __future__ import annotations

import threading
import time

import pytest

from app.domain import translate as tr


def test_google_batch_is_serial_instead_of_bursting_the_free_endpoint(monkeypatch) -> None:
    in_flight = 0
    peak = 0
    lock = threading.Lock()

    def fake_google(text, target, source="auto", client=None):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.01)
        with lock:
            in_flight -= 1
        return f"[{target}] {text}"

    monkeypatch.setattr(tr, "google_translate", fake_google)
    monkeypatch.setattr(tr, "_GOOGLE_MIN_INTERVAL_SECONDS", 0)

    texts = [f"cue {i}" for i in range(16)]
    started = time.perf_counter()
    out = tr.translate_many(None, texts, "en", user_id=None)
    _elapsed = time.perf_counter() - started

    assert out == [f"[en] cue {i}" for i in range(16)], "串行流控不能改变字幕顺序"
    assert peak == 1, "免费端点不该收到并发突发请求"


def test_ai_concurrency_is_bounded(monkeypatch) -> None:
    in_flight = 0
    peak = 0
    lock = threading.Lock()

    def fake_ai(chat_target, text, target, client=None, call=None):
        nonlocal in_flight, peak
        with lock:
            in_flight += 1
            peak = max(peak, in_flight)
        time.sleep(0.05)
        with lock:
            in_flight -= 1
        return text

    class Billing:
        def __enter__(self): return None
        def __exit__(self, *_args): return False

    monkeypatch.setattr(tr, "resolve_ai_chat_target", lambda *args, **kwargs: object())
    monkeypatch.setattr(tr, "ai_translate_with", fake_ai)
    monkeypatch.setattr(tr, "billable", lambda *args, **kwargs: Billing())
    tr.translate_many(None, [f"c{i}" for i in range(64)], "en", user_id=None, engine="ai")
    assert 1 < peak <= tr._MAX_PARALLEL


def test_google_batch_disables_retry_storm(monkeypatch) -> None:
    seen: list[int | None] = []

    class Client:
        def __init__(self, *args, max_retries=None, **kwargs):
            seen.append(max_retries)
        def __enter__(self): return self
        def __exit__(self, *_args): return False

    monkeypatch.setattr(tr.ai_retry, "RetryingClient", Client)
    monkeypatch.setattr(tr, "google_translate", lambda text, target, source="auto", client=None: text)
    monkeypatch.setattr(tr, "_GOOGLE_MIN_INTERVAL_SECONDS", 0)
    assert tr.translate_many(None, ["a", "b"], "en", user_id=None) == ["a", "b"]
    assert seen == [0]


def test_empty_cues_pass_through_without_a_network_call(monkeypatch) -> None:
    calls: list[str] = []

    def fake_google(text, target, source="auto", client=None):
        calls.append(text)
        return f"T:{text}"

    monkeypatch.setattr(tr, "google_translate", fake_google)
    monkeypatch.setattr(tr, "_GOOGLE_MIN_INTERVAL_SECONDS", 0)
    out = tr.translate_many(None, ["hello", "", "   ", "world"], "en", user_id=None)
    assert out == ["T:hello", "", "", "T:world"]
    assert calls == ["hello", "world"], "blank cues must not cost a round-trip"


def test_one_failure_fails_the_batch(monkeypatch) -> None:
    def fake_google(text, target, source="auto", client=None):
        if text == "bad":
            raise tr.TranslateError("boom")
        return text

    monkeypatch.setattr(tr, "google_translate", fake_google)
    monkeypatch.setattr(tr, "_GOOGLE_MIN_INTERVAL_SECONDS", 0)
    with pytest.raises(tr.TranslateError):
        tr.translate_many(None, ["ok", "bad", "ok2"], "en", user_id=None)


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
        tr.translate_many(FakeSession(), ["a", "b", "c"], "en", user_id=None, engine="ai")
    assert reads, "provider was never resolved"
    assert all(name == threading.current_thread().name for name in reads), (
        "the DB was read from a worker thread"
    )
