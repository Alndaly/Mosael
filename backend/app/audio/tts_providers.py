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
