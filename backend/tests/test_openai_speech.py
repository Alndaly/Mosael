"""OpenAI 语音 Adapter:缺钥匙当场拒绝、语速交给模型自己把握。"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ai.providers import OpenAISpeechAdapter, SpeechSynthesisError, SpeechSynthesisRequest


class TestOpenAI:
    def test_a_missing_key_fails_before_any_request(self) -> None:
        with pytest.raises(SpeechSynthesisError, match="API Key"):
            OpenAISpeechAdapter(api_key="")

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

        # 拦的是 client 的 post,不是模块级的 httpx.post —— 适配器现在走 RetryingClient
        # (它是 httpx.Client 的子类,重试挂在 send 上)。
        monkeypatch.setattr("httpx.Client.post", lambda self, url, **kw: fake_post(url, **kw))
        OpenAISpeechAdapter(api_key="k").synthesize(SpeechSynthesisRequest(text="hi", speed=1.25), tmp_path / "o.wav")
        assert captured["speed"] == pytest.approx(1.25)

    def test_natural_pace_sends_no_speed_at_all(self, monkeypatch, tmp_path: Path) -> None:
        captured: dict = {}

        class FakeResponse:
            content = b"RIFF"

            def raise_for_status(self):
                return None

        monkeypatch.setattr(
            "httpx.Client.post",
            lambda self, url, **kw: (captured.update(kw["json"]), FakeResponse())[1],
        )
        OpenAISpeechAdapter(api_key="k").synthesize(SpeechSynthesisRequest(text="hi"), tmp_path / "o.wav")
        assert "speed" not in captured
