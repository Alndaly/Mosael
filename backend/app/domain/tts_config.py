"""Runtime config for voice cloning (TTS). DB singleton (TtsConfig id='default')
overrides the OPEN_STUDIO_TTS_* env fallback so engine / interpreter / download source /
Fish Speech source+weights dirs are editable from Settings. Cached; call refresh()
after a write."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings

SINGLETON_ID = "default"

# Model-download source → the HF endpoint the worker/download subprocess should use.
HF_ENDPOINTS = {
    "hf": "https://huggingface.co",
    "hf-mirror": "https://hf-mirror.com",
    "modelscope": "https://huggingface.co",  # f5-tts pulls from HF; modelscope is a fish path
}

# App-managed Fish Speech install: the one-click download fetches the official source
# checkout + s2-pro weights here, so real synthesis works on a fresh machine without any
# manual path config (Settings paths still override, sibling mibu-video is a dev fallback).
MANAGED_FISH_REPO = settings.data_dir / "tts" / "fish-speech-src"
MANAGED_FISH_MODEL = settings.data_dir / "tts" / "fish-speech-s2-pro"
# Marker files that prove each managed dir is a real checkout / real weights (not a
# half-cloned or empty dir): a module the worker actually imports, and the codec weights.
# (fish_speech is an implicit-namespace package — no root __init__.py — so anchor deeper.)
FISH_REPO_MARKER = "fish_speech/utils/schema.py"
FISH_MODEL_MARKER = "codec.pth"

# Dev convenience: reuse a sibling mibu-video checkout's Fish Speech setup (source
# clone + already-downloaded weights) so real synthesis works without re-downloading.
_OPEN_STUDIO_NEW_ROOT = Path(__file__).resolve().parents[3]
_SIBLING_VIDEO = _OPEN_STUDIO_NEW_ROOT.parent / "mibu-video" / "backend"
_SIBLING_FISH_REPO = _SIBLING_VIDEO / "third_party" / "fish-speech"
_SIBLING_FISH_MODEL = _SIBLING_VIDEO / "models" / "tts" / "fish-speech-s2-pro"


def _resolve(configured: str, defaults: tuple[Path, ...], *, marker: str | None = None) -> str:
    """Configured path wins; else the first default that exists (and, when `marker` is
    given, actually contains that file). Empty string if nothing resolves."""
    if configured.strip():
        return str(Path(configured).expanduser())
    for default in defaults:
        if default.is_dir() and (marker is None or (default / marker).is_file()):
            return str(default)
    return ""


@dataclass(frozen=True)
class TtsRuntimeConfig:
    engine: str
    python_path: str
    source: str
    fish_repo_dir: str
    fish_model_dir: str

    @property
    def hf_endpoint(self) -> str:
        return HF_ENDPOINTS.get(self.source, "https://hf-mirror.com")

    @property
    def resolved_fish_repo(self) -> str:
        return _resolve(
            self.fish_repo_dir, (MANAGED_FISH_REPO, _SIBLING_FISH_REPO), marker=FISH_REPO_MARKER
        )

    @property
    def resolved_fish_model(self) -> str:
        return _resolve(
            self.fish_model_dir, (MANAGED_FISH_MODEL, _SIBLING_FISH_MODEL), marker=FISH_MODEL_MARKER
        )


_lock = threading.Lock()
_cached: TtsRuntimeConfig | None = None


def _load() -> TtsRuntimeConfig:
    from sqlalchemy.exc import SQLAlchemyError

    from app.core.db import SessionLocal
    from app.db.models import TtsConfig

    try:
        with SessionLocal() as db:
            row = db.get(TtsConfig, SINGLETON_ID)
            if row is not None:
                return TtsRuntimeConfig(
                    engine=row.engine,
                    python_path=row.python_path,
                    source=row.source,
                    fish_repo_dir=row.fish_repo_dir or "",
                    fish_model_dir=row.fish_model_dir or "",
                )
    except SQLAlchemyError:
        # Table not migrated yet (fresh DB) — the singleton is optional; env defaults apply.
        pass
    return TtsRuntimeConfig(
        engine=settings.tts_engine,
        python_path=settings.tts_python,
        source="hf-mirror",
        fish_repo_dir="",
        fish_model_dir="",
    )


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
