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

from app.audio.tts_providers import (
    EDGE_BUILTIN_VOICES,
    EdgeTTS,
    SpeechRequest,
    TTSError,
    build_remote_provider,
    describe_engines,
)
from tests.util import fresh_client


def _client():
    client = fresh_client()
    client.post("/api/workspaces", json={"name": "W"})
    return client


def test_edge_is_offered_without_a_key() -> None:
    """The whole point of the engine: usable before anything is configured."""
    entry = next(e for e in describe_engines() if e["id"] == "edge")
    assert entry["needs_key"] is False
    assert entry["voices"], "an empty dropdown would read as 'this engine has no voices'"


def test_edge_voices_come_from_the_builtin_catalogue() -> None:
    client = _client()
    res = client.get("/api/tts/voices?engine=edge")
    assert res.status_code == 200, res.text
    voices = res.json()
    assert [v["value"] for v in voices] == [v for v, _ in EDGE_BUILTIN_VOICES]
    assert voices[0]["label"] != voices[0]["value"], "labels should be readable"


def test_provider_builds_with_no_credentials() -> None:
    provider = build_remote_provider("edge", api_key="")
    assert isinstance(provider, EdgeTTS)
    assert provider.parallel_safe, "remote HTTP engine — batches must be allowed to fan out"


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
    """SpeechRequest.speed must mean the same thing across engines — dubbing depends on it."""
    out = tmp_path / "a.mp3"
    EdgeTTS().synthesize(SpeechRequest(text="你好", voice="zh-CN-YunxiNeural", speed=1.2), out)
    assert fake_communicate.calls == [{"text": "你好", "voice": "zh-CN-YunxiNeural", "rate": "+20%"}]
    assert out.read_bytes() == b"fake-mp3"


def test_missing_voice_falls_back_to_a_default(fake_communicate, tmp_path) -> None:
    """An empty voice id must synthesise, not 400 — the panel may submit before a pick."""
    EdgeTTS().synthesize(SpeechRequest(text="hi"), tmp_path / "b.mp3")
    assert fake_communicate.calls[0]["voice"] == "zh-CN-XiaoxiaoNeural"
    assert fake_communicate.calls[0]["rate"] == "+0%"


def test_empty_audio_is_an_error_not_a_silent_asset(fake_communicate, tmp_path) -> None:
    """A zero-byte file registered as an asset would fail much later, in the timeline."""
    fake_communicate.write_bytes = b""
    with pytest.raises(TTSError, match="空音频"):
        EdgeTTS().synthesize(SpeechRequest(text="你好"), tmp_path / "c.mp3")
