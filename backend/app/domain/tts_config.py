"""Runtime config for voice cloning (TTS). DB singleton (TtsConfig id='default')
overrides the MIBU_TTS_* env fallback so engine / interpreter / download source
are editable from Settings. Cached; call refresh() after a write."""
from __future__ import annotations

import threading
from dataclasses import dataclass

from app.core.config import settings

SINGLETON_ID = "default"

# Model-download source → the HF endpoint the worker/download subprocess should use.
HF_ENDPOINTS = {
    "hf": "https://huggingface.co",
    "hf-mirror": "https://hf-mirror.com",
    "modelscope": "https://huggingface.co",  # f5-tts pulls from HF; modelscope is a fish path
}


@dataclass(frozen=True)
class TtsRuntimeConfig:
    engine: str
    python_path: str
    source: str

    @property
    def hf_endpoint(self) -> str:
        return HF_ENDPOINTS.get(self.source, "https://hf-mirror.com")


_lock = threading.Lock()
_cached: TtsRuntimeConfig | None = None


def _load() -> TtsRuntimeConfig:
    from app.core.db import SessionLocal
    from app.db.models import TtsConfig

    with SessionLocal() as db:
        row = db.get(TtsConfig, SINGLETON_ID)
        if row is not None:
            return TtsRuntimeConfig(engine=row.engine, python_path=row.python_path, source=row.source)
    return TtsRuntimeConfig(engine=settings.tts_engine, python_path=settings.tts_python, source="hf-mirror")


def get() -> TtsRuntimeConfig:
    global _cached
    with _lock:
        if _cached is None:
            _cached = _load()
        return _cached


def refresh() -> None:
    global _cached
    with _lock:
        _cached = None
