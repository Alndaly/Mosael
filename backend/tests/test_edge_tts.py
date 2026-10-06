"""Edge 免费语音:the zero-config engine.

Every other engine demands something before it speaks — clone wants gigabytes of local
weights, OpenAI/火山 want keys from a console. Edge is the one a fresh install can use
immediately, so these tests pin the promises that make that true: it appears in the engine
list without needing a key, its voice dropdown is populated from the built-in catalogue, and
building the provider with no credentials succeeds. Synthesis itself is mocked — the real
service is a network dependency the suite must not have.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.providers import (
    EDGE_BUILTIN_VOICES,
    EdgeSpeechAdapter,
    SpeechSynthesisRequest,
    SpeechSynthesisError,
    build_speech_adapter,
)
from app.domain.voices.engine_catalog import describe_engines
from tests.util import fresh_client


def _client():
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    return client


def test_edge_is_offered_without_a_key() -> None:
    """The whole point of the engine: usable before anything is configured."""
    entry = next(e for e in describe_engines(None) if e["id"] == "builtin:edge")
    assert entry["needs_key"] is False
    assert entry["voices"], "an empty dropdown would read as 'this engine has no voices'"


def test_edge_voices_come_from_the_builtin_catalogue() -> None:
    client = _client()
    res = client.get("/api/tts/voices?engine=builtin:edge")
    assert res.status_code == 200, res.text
    voices = res.json()
    assert [v["value"] for v in voices] == [v for v, _ in EDGE_BUILTIN_VOICES]
    assert voices[0]["label"] != voices[0]["value"], "labels should be readable"


def test_provider_builds_with_no_credentials() -> None:
    provider = build_speech_adapter("edge", api_key="")
    assert isinstance(provider, EdgeSpeechAdapter)
    assert provider.supports_parallel_synthesis, "remote HTTP engine — batches must be allowed to fan out"


class _FakeCommunicate:
    """Captures the arguments synthesis passes to edge_tts and writes fake audio."""

    calls: list[dict] = []
    write_bytes: bytes = b"fake-mp3"

    def __init__(self, text: str, voice: str = "", rate: str = "") -> None:
        type(self).calls.append({"text": text, "voice": voice, "rate": rate})
        self._out: Path | None = None

    async def save(self, path: str) -> None:
        Path(path).write_bytes(type(self).write_bytes)


@pytest.fixture()
def fake_communicate(monkeypatch):
    import edge_tts

    _FakeCommunicate.calls = []
    _FakeCommunicate.write_bytes = b"fake-mp3"
    monkeypatch.setattr(edge_tts, "Communicate", _FakeCommunicate)
    return _FakeCommunicate


def test_speed_maps_to_a_signed_rate_percentage(fake_communicate, tmp_path) -> None:
    """SpeechSynthesisRequest.speed must mean the same thing across engines — dubbing depends on it."""
    out = tmp_path / "a.mp3"
    EdgeSpeechAdapter().synthesize(SpeechSynthesisRequest(text="你好", voice="zh-CN-YunxiNeural", speed=1.2), out)
    assert fake_communicate.calls == [{"text": "你好", "voice": "zh-CN-YunxiNeural", "rate": "+20%"}]
    assert out.read_bytes() == b"fake-mp3"


def test_missing_voice_falls_back_to_a_default(fake_communicate, tmp_path) -> None:
    """An empty voice id must synthesise, not 400 — the panel may submit before a pick."""
    EdgeSpeechAdapter().synthesize(SpeechSynthesisRequest(text="hi"), tmp_path / "b.mp3")
    assert fake_communicate.calls[0]["voice"] == "zh-CN-XiaoxiaoNeural"
    assert fake_communicate.calls[0]["rate"] == "+0%"


def test_empty_audio_is_an_error_not_a_silent_asset(fake_communicate, tmp_path) -> None:
    """A zero-byte file registered as an asset would fail much later, in the timeline."""
    fake_communicate.write_bytes = b""
    with pytest.raises(SpeechSynthesisError, match="空音频"):
        EdgeSpeechAdapter().synthesize(SpeechSynthesisRequest(text="你好"), tmp_path / "c.mp3")


class _Flaky(_FakeCommunicate):
    """前几次连不上(付费实测里那句原话),之后照常交回音频。"""

    failures: list[BaseException] = []

    async def save(self, path: str) -> None:
        if type(self).failures:
            raise type(self).failures.pop(0)
        await super().save(path)


@pytest.fixture()
def flaky(monkeypatch):
    import edge_tts

    from app.ai.providers.adapters.microsoft import edge_speech

    _Flaky.calls, _Flaky.write_bytes, _Flaky.failures = [], b"fake-mp3", []
    monkeypatch.setattr(edge_tts, "Communicate", _Flaky)
    monkeypatch.setattr(edge_speech, "backoff_seconds", lambda attempt: 0)
    return _Flaky


def test_连不上就再连一次_免费的配音一失败_同一条流程里付过钱的东西跟着作废(flaky, tmp_path) -> None:
    """付费实测:带货口播第 5 拍连 speech.platform.bing.com 超时,整条循环失败,前 4 拍 ¥8.47 的画面和视频没能导出。"""
    import aiohttp

    flaky.failures = [aiohttp.ServerTimeoutError("Connection timeout to host wss://speech.platform.bing.com/...")]
    out = tmp_path / "d.mp3"
    EdgeSpeechAdapter().synthesize(SpeechSynthesisRequest(text="中间一颗银转运珠"), out)
    assert len(flaky.calls) == 2 and out.read_bytes() == b"fake-mp3"


def test_重连次数跟着出站调用的重试设置_用完了照旧报错(flaky, tmp_path, monkeypatch) -> None:
    from app.core import http_retry

    monkeypatch.setattr(http_retry, "_max_retries", 1)
    flaky.failures = [TimeoutError("timeout"), TimeoutError("timeout"), TimeoutError("timeout")]
    with pytest.raises(SpeechSynthesisError, match="timeout"):
        EdgeSpeechAdapter().synthesize(SpeechSynthesisRequest(text="你好"), tmp_path / "e.mp3")
    assert len(flaky.calls) == 2, "设置是重试 1 次:一共连两次"


def test_服务回了没有音频_不是连接问题_不重来(flaky, tmp_path) -> None:
    from edge_tts.exceptions import NoAudioReceived

    flaky.failures = [NoAudioReceived("No audio was received")]
    with pytest.raises(SpeechSynthesisError):
        EdgeSpeechAdapter().synthesize(SpeechSynthesisRequest(text="你好", voice="zh-CN-NoSuchNeural"), tmp_path / "f.mp3")
    assert len(flaky.calls) == 1


def test_每个引擎都说得出自己能不能用() -> None:
    """「这个引擎现在能不能用」是**所有**引擎都要回答的问题。

    它曾经只长在克隆那一条上,而只列就绪引擎的那个下拉(工作流节点的「引擎」)按它过滤 ——
    于是除了克隆,一个都不剩,音色跟着也空了。真机截图抓到的。
    """
    from app.core.db import SessionLocal
    from app.domain.voices.engine_catalog import describe_engines
    from tests.util import fresh_client

    fresh_client()
    with SessionLocal() as db:
        engines = describe_engines(db)
    assert engines, "引擎目录是空的"
    for engine in engines:
        assert isinstance(engine.get("ready"), bool), f"{engine['id']} 没说自己能不能用"
    by_id = {str(engine["id"]): engine for engine in engines}
    #: 不要钥匙的随时能用;要钥匙而这个人没配的,不列出来 —— 列出来只会让人选中之后才失败。
    assert by_id["builtin:edge"]["ready"] is True
    assert by_id["builtin:openai"]["ready"] is False


def test_没配连接时引擎清单只剩不要钥匙的那几个() -> None:
    from app.core.db import SessionLocal
    from app.domain.workflows.field_options import OptionContext, field_options
    from tests.util import fresh_client

    client = fresh_client()
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        options = field_options(db, "speech_engines", OptionContext(workspace_id=workspace, user_id=None, parent="", locale="zh"))
    values = [one["value"] for one in options]
    assert values[0] == "builtin:clone", "克隆总在最前"
    assert "builtin:edge" in values, "不要钥匙的引擎必须列得出来(真机上这里只剩了克隆)"
