"""OpenAI 的语音端点。"""

from __future__ import annotations

from pathlib import Path

import httpx

from app.core.http_retry import RetryingClient

from app.ai.providers.contracts.speech import SPEECH_REQUEST_TIMEOUT_SECONDS, SpeechSynthesisRequest, SpeechSynthesisError


class OpenAISpeechAdapter:
    """OpenAI's speech endpoint. Stock voices, no reference clip, no local model."""

    #: 引擎 id **就是 vendor id**(domain/voices/voices.py 拿 engine 去 resolve_connection)。
    #: 合并成 "openai" 之前这里有三个:openai-tts 与 openai-compatible-tts —— 而后者存在的
    #: 理由只是"要填自定义 endpoint",可 openai 档案本来就有 base_url 字段。
    engine_id = "openai"
    label_key = "ttsProvider_openai"
    supports_parallel_synthesis = True
    VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")

    def __init__(self, api_key: str, model: str = "gpt-4o-mini-tts", base_url: str = "") -> None:
        if not api_key:
            raise SpeechSynthesisError("OpenAI 语音合成需要 API Key,请在设置里配置")
        self._key = api_key
        self._model = model
        self._base = (base_url or "https://api.openai.com/v1").rstrip("/")

    def synthesize(self, request: SpeechSynthesisRequest, out_path: Path) -> None:
        payload = {
            "model": self._model,
            "input": request.text,
            "voice": request.voice or "alloy",
            "response_format": "wav",
        }
        # The API takes speed directly, which is what we want for dubbing — the model paces
        # itself rather than us squeezing the waveform afterwards.
        if abs(request.speed - 1.0) > 0.01:
            payload["speed"] = max(0.25, min(4.0, request.speed))
        try:
            with RetryingClient(timeout=SPEECH_REQUEST_TIMEOUT_SECONDS) as client:
                response = client.post(
                    f"{self._base}/audio/speech",
                    headers={"Authorization": f"Bearer {self._key}"},
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SpeechSynthesisError(f"OpenAI 语音合成失败: {exc}") from exc
        out_path.write_bytes(response.content)


