"""批量翻译按引擎采用不同的流控。

AI 供应商有正式配额，可以有限并发；Google 免费端点会限制客户端标识、出口或突发请求，只能串行。这里
同时钉住顺序、空字幕占位，以及 DB 不进入工作线程。"""

from __future__ import annotations

import threading
import time

import pytest

from app.domain import translate as tr
from app.domain.capabilities import Provider


@pytest.fixture(autouse=True)
def _named_builtin(monkeypatch: pytest.MonkeyPatch) -> None:
    """这里只看批量的流控:挑哪一家(能力表)另有测试,直接给点名的那一家(没点名就是 Google)。"""
    monkeypatch.setattr(tr.capabilities, "pick",
                        lambda _db, _owner, _cap, provider_id, **_: Provider(id=provider_id or tr.GOOGLE, name="", builtin=True))


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

    from types import SimpleNamespace

    #: 直连目标(批量共用一条 HTTP 连接的那一种)。
    monkeypatch.setattr(tr, "resolve_ai_chat_target", lambda *args, **kwargs: SimpleNamespace(execution_surface="direct"))
    monkeypatch.setattr(tr, "ai_translate_with", fake_ai)
    monkeypatch.setattr(tr, "billable", lambda *args, **kwargs: Billing())
    tr.translate_many(None, [f"c{i}" for i in range(64)], "en", user_id=None, engine="builtin:chat")
    assert 1 < peak <= tr._MAX_PARALLEL


def test_google_batch_disables_retry_storm(monkeypatch) -> None:
    seen: list[int | None] = []

    class Client:
        def __init__(self, *args, max_retries=None, **kwargs):
            seen.append(max_retries)
        def __enter__(self): return self
        def __exit__(self, *_args): return False

    monkeypatch.setattr(tr.http_retry, "RetryingClient", Client)
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
        #: 点名一条连接:没点名时没有主人就没有「他的连接」,根本不读库,这条断言就测不到什么。
        tr.translate_many(FakeSession(), ["a", "b", "c"], "en", user_id=None, engine="builtin:chat", profile_id="p")
    assert reads, "provider was never resolved"
    assert all(name == threading.current_thread().name for name in reads), (
        "the DB was read from a worker thread"
    )


def _ai_batch(monkeypatch, fake_ai) -> None:
    from types import SimpleNamespace

    class Billing:
        def __enter__(self): return None
        def __exit__(self, *_args): return False

    monkeypatch.setattr(tr, "resolve_ai_chat_target", lambda *args, **kwargs: SimpleNamespace(execution_surface="direct"))
    monkeypatch.setattr(tr, "ai_translate_with", fake_ai)
    monkeypatch.setattr(tr, "billable", lambda *args, **kwargs: Billing())


def test_一句失败_还没开始的句子不再翻(monkeypatch) -> None:
    """此前 pool.map 要把排进去的每一句都跑完才抛 —— 一句失败,其余几百句照样一句句付费翻完、再一起扔掉。"""
    called: list[str] = []
    lock = threading.Lock()

    def fake_ai(chat_target, text, target, client=None, call=None):
        with lock:
            called.append(text)
        if text == "c0":
            raise tr.TranslateError("translateErr_noProvider")
        time.sleep(0.05)
        return text

    _ai_batch(monkeypatch, fake_ai)
    with pytest.raises(tr.TranslateError) as failed:
        tr.translate_many(None, [f"c{i}" for i in range(64)], "en", user_id=None, engine="builtin:chat")
    assert failed.value.key == "translateErr_noProvider", "报的是那一句真的失败"
    assert len(called) <= 2 * tr._MAX_PARALLEL, f"失败之后又翻了 {len(called)} 句"


#: 第几句开始时说停。由替身自己在那一句里立信号,不用计时器:此前是 0.1 秒后的 Timer,计时器线程起得晚,
#: 说停的那一刻就晚,后面数出来的句数跟着变。
_STOP_AT = 16
_SENTENCES = 400


def _stopped_late(called: list[str]) -> None:
    """说停之后还起了几句;线画在「不停的话会起几句」的一半(调用方每隔一拍才问一次停不停,在途的照样跑完)。"""
    late = len(called) - _STOP_AT
    assert late < (_SENTENCES - _STOP_AT) / 2, f"说停之后还翻了 {late} 句"


def test_调用方说停_不再起新的句子(monkeypatch) -> None:
    """工作流里同一张图别的节点失败了(或这一轮被取消):翻译节点不该把剩下的句子一句句付费翻完。"""
    called: list[str] = []
    lock = threading.Lock()
    stop = threading.Event()

    def fake_ai(chat_target, text, target, client=None, call=None):
        with lock:
            called.append(text)
            if len(called) == _STOP_AT:
                stop.set()
        time.sleep(0.05)
        return text

    _ai_batch(monkeypatch, fake_ai)
    with pytest.raises(tr.TranslationStopped):
        tr.translate_many(None, [f"c{i}" for i in range(_SENTENCES)], "en", user_id=None, engine="builtin:chat",
                          stop=stop.is_set)
    _stopped_late(called)


def test_逐句翻译节点_这一轮在停就停下_说的是在停(monkeypatch) -> None:
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.executors.ai import translate_lines
    from app.domain.workflows.run_scope import halt_scope

    called: list[str] = []
    lock = threading.Lock()
    halts: list[threading.Event] = []

    def fake_ai(chat_target, text, target, client=None, call=None):
        with lock:
            called.append(text)
            if len(called) == _STOP_AT:
                halts[0].set()
        time.sleep(0.05)
        return text

    _ai_batch(monkeypatch, fake_ai)
    with halt_scope() as halt:
        halts.append(halt)
        with pytest.raises(WorkflowDomainError) as stopped:
            translate_lines(None, None, {"texts": [f"c{i}" for i in range(_SENTENCES)], "target_lang": "en",
                                         "engine": "builtin:chat"})
    assert stopped.value.key == "wfErr_cancelled"
    _stopped_late(called)
