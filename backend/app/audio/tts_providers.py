"""Speech synthesis behind one interface, so the caller does not care which engine ran.

Until now synthesis meant exactly one thing: a local zero-shot clone (F5 / Fish Speech) driven
by a reference clip. That is the right engine when you want *this person's* voice, and the wrong
one for everything else — it needs a reference recording, a multi-gigabyte model on disk, and a
GPU's patience. A remote engine needs none of that and speaks immediately in a stock voice.

The distinction that actually matters to callers is `parallel_safe`. A remote engine is an HTTP
request, so N cues can be in flight at once; a local engine holds one model in memory and
running two at once only makes both slower and risks exhausting VRAM. Dubbing a video means
synthesising every cue in a transcript, so getting this wrong is the difference between seconds
and many minutes — see synthesize_many, which is the only place callers should batch.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import base64
import json
import uuid

import httpx

logger = logging.getLogger(__name__)

REMOTE_TIMEOUT_SECONDS = 120
#: Concurrency for remote engines. Bounded: providers rate-limit, and a long transcript would
#: otherwise open a socket per cue.
REMOTE_PARALLEL = 6


class TTSError(RuntimeError):
    """Raised when synthesis cannot produce audio."""


@dataclass(frozen=True)
class SpeechRequest:
    """One utterance to synthesise.

    `speed` exists for dubbing: a translated line rarely fits the window its original occupied,
    and asking the engine to speak faster produces better prosody than stretching the waveform
    afterwards. 1.0 means the engine's natural pace.
    """

    text: str
    voice: str = ""  # engine-specific voice id; ignored by clone engines
    speed: float = 1.0


class TTSProvider(Protocol):
    id: str
    label: str
    #: May several synthesize() calls run at once? True for remote HTTP engines, false for a
    #: local model that holds one instance in memory.
    parallel_safe: bool

    def synthesize(self, request: SpeechRequest, out_path: Path) -> None: ...


class OpenAITTS:
    """OpenAI's speech endpoint. Stock voices, no reference clip, no local model."""

    id = "openai"
    label = "OpenAI"
    parallel_safe = True
    VOICES = ("alloy", "echo", "fable", "onyx", "nova", "shimmer")

    def __init__(self, api_key: str, model: str = "gpt-4o-mini-tts", base_url: str = "") -> None:
        if not api_key:
            raise TTSError("OpenAI 语音合成需要 API Key,请在设置里配置")
        self._key = api_key
        self._model = model
        self._base = (base_url or "https://api.openai.com/v1").rstrip("/")

    def synthesize(self, request: SpeechRequest, out_path: Path) -> None:
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
            response = httpx.post(
                f"{self._base}/audio/speech",
                headers={"Authorization": f"Bearer {self._key}"},
                json=payload,
                timeout=REMOTE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise TTSError(f"OpenAI 语音合成失败: {exc}") from exc
        out_path.write_bytes(response.content)


def synthesize_many(
    provider: TTSProvider,
    requests: list[SpeechRequest],
    out_paths: list[Path],
) -> list[Exception | None]:
    """Synthesise a batch, concurrently only where the engine allows it.

    Returns one entry per request — the exception if that one failed, None if it succeeded.
    Failures are per-cue on purpose: dubbing a hundred-line transcript should not be lost
    because line 57 tripped a rate limit, and the caller needs to know *which* lines to retry.
    """
    if len(requests) != len(out_paths):
        raise ValueError("requests and out_paths must be the same length")
    results: list[Exception | None] = [None] * len(requests)

    def one(index: int) -> None:
        try:
            provider.synthesize(requests[index], out_paths[index])
        except Exception as exc:  # noqa: BLE001 — recorded per cue, not raised
            logger.warning("tts cue %d failed: %s", index, exc)
            results[index] = exc

    if provider.parallel_safe and len(requests) > 1:
        workers = min(REMOTE_PARALLEL, len(requests))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(one, range(len(requests))))
    else:
        # A local model engine: one at a time, deliberately. Running two only makes both slower
        # and can exhaust VRAM.
        for index in range(len(requests)):
            one(index)
    return results


class VolcanoTTS:
    """火山引擎(豆包)大模型语音合成 — the v3 synchronous endpoint.

    Best Chinese voices of the engines here, at the cost of a fiddlier contract than OpenAI's:

    * X-Api-Resource-Id must match the voice's family or the call fails with code 55000000, and
      the family is only discoverable from the voice id itself — see _resource_id.
    * The response is a chunked stream of JSON lines, each carrying a base64 audio fragment;
      code 20000000 is the end-of-stream marker, not an error.
    * Speed is `speech_rate`, an int in [-50, 100] where 0 is natural — not a multiplier. The
      linear map below is what makes SpeechRequest.speed mean the same thing across engines,
      which is what dubbing depends on.
    """

    id = "volcano"
    label = "火山方舟(豆包)"
    parallel_safe = True

    def __init__(self, api_key: str, voice: str = "", model: str = "", base_url: str = "") -> None:
        if not api_key:
            raise TTSError("火山引擎语音合成需要新版控制台的 API Key")
        self._key = api_key
        self._model = model
        self._base = (base_url or "https://openspeech.bytedance.com").rstrip("/")
        self._default_voice = voice

    def _resource_id(self, voice: str) -> str:
        """The voice family, which the header must agree with. An explicit seed-* model wins."""
        if self._model.startswith("seed-"):
            return self._model
        if voice.startswith("S_"):
            return "seed-icl-2.0"  # 复刻音色
        if "_uranus_" in voice or voice.startswith("saturn_"):
            return "seed-tts-2.0"
        return "seed-tts-1.0"

    def synthesize(self, request: SpeechRequest, out_path: Path) -> None:
        voice = request.voice or self._default_voice
        if not voice:
            raise TTSError("火山引擎语音合成需要音色 id(如 zh_male_..._bigtts)")
        speed = max(0.2, min(3.0, request.speed))
        payload = {
            "req_params": {
                "text": request.text,
                "speaker": voice,
                "audio_params": {
                    "format": "mp3",
                    "sample_rate": 24000,
                    "speech_rate": max(-50, min(100, round((speed - 1.0) * 100))),
                },
            }
        }
        headers = {
            "X-Api-Key": self._key,
            "X-Api-Resource-Id": self._resource_id(voice),
            "X-Api-Request-Id": uuid.uuid4().hex,
            "Content-Type": "application/json",
        }
        chunks: list[bytes] = []
        try:
            with httpx.Client(timeout=REMOTE_TIMEOUT_SECONDS) as client:
                with client.stream(
                    "POST", f"{self._base}/api/v3/tts/unidirectional", headers=headers, json=payload
                ) as response:
                    response.raise_for_status()
                    for line in response.iter_lines():
                        line = (line or "").strip()
                        if not line:
                            continue
                        try:
                            frame = json.loads(line)
                        except ValueError:
                            continue  # heartbeat / separator, not a frame
                        code = int(frame.get("code", 0))
                        if code == 20000000:  # documented end-of-stream, not a failure
                            break
                        if code != 0:
                            raise TTSError(
                                f"火山 TTS 失败: code={code} {frame.get('message') or ''}".strip()
                            )
                        data = frame.get("data")
                        if data:
                            chunks.append(base64.b64decode(data))
        except httpx.HTTPError as exc:
            raise TTSError(f"火山 TTS 请求失败: {exc}") from exc
        if not chunks:
            raise TTSError("火山 TTS 返回空音频")
        out_path.write_bytes(b"".join(chunks))


#: Engines a user can pick, in the order the UI offers them. "clone" is handled separately —
#: it is the local reference-driven path and needs a Voice row, not an engine voice id.
REMOTE_ENGINES = {
    OpenAITTS.id: OpenAITTS,
    VolcanoTTS.id: VolcanoTTS,
}


def describe_engines() -> list[dict[str, object]]:
    """What the UI needs to render an engine picker, without importing the classes."""
    return [
        {
            "id": "clone",
            "label": "本地音色克隆",
            "needs_key": False,
            "needs_voice_id": False,
            "voices": [],
            "note": "用音色库里的克隆音色;需要本地引擎(F5 / Fish Speech)。",
        },
        {
            "id": OpenAITTS.id,
            "label": OpenAITTS.label,
            "needs_key": True,
            "needs_voice_id": False,
            "voices": list(OpenAITTS.VOICES),
            "note": "预置音色,不需要参考音频。",
        },
        {
            "id": VolcanoTTS.id,
            "label": VolcanoTTS.label,
            "needs_key": True,
            # No fixed list: the catalogue is large and account-dependent, so the voice id is
            # typed in. Guessing a list here would go stale and mislead.
            "needs_voice_id": True,
            "voices": [],
            "note": "中文音色最好;需填音色 id(如 zh_male_..._bigtts)。",
        },
    ]


def build_remote_provider(engine: str, api_key: str, voice: str = "", model: str = "", base_url: str = ""):
    """Construct a remote engine, or raise a message the user can act on."""
    cls = REMOTE_ENGINES.get(engine)
    if cls is None:
        raise TTSError(f"未知的语音引擎:{engine}")
    if cls is OpenAITTS:
        return cls(api_key=api_key, model=model or "gpt-4o-mini-tts", base_url=base_url)
    return cls(api_key=api_key, voice=voice, model=model, base_url=base_url)
