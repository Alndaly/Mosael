"""语音引擎的共用契约。

和 `ai/providers/base.py` 是同一件事的两侧:那边是图像/视频的适配器契约,这边是语音的。
两边此前的差别只在**摆放**——那边一家一个文件,这边六家挤在一个 670 行的模块里,而这个
不对称没有任何理由支撑它(见 docs 里的生成体系剖面 F4)。
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


