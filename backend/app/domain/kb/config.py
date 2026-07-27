from __future__ import annotations

import threading
from dataclasses import dataclass

from app.core.config import settings

"""Effective KB embedding config.

The DB singleton (KbEmbeddingConfig id='default') overrides the
OPEN_STUDIO_KB_EMBEDDING_* env fallback, so the vector tier can be configured from
the UI. Resolved once and cached; call refresh() after writing the row (or
after deleting the selected provider profile)."""

SINGLETON_ID = "default"


@dataclass(frozen=True)
class EmbeddingConfig:
    provider_profile_id: str | None
    vendor: str  # resolution fallback when no profile_id is pinned
    model: str
    dim: int

    @property
    def enabled(self) -> bool:
        return bool(self.model and (self.provider_profile_id or self.vendor))


_lock = threading.Lock()
_cached: EmbeddingConfig | None = None


def _load() -> EmbeddingConfig:
    from app.core.db import SessionLocal
    from app.db.models import KbEmbeddingConfig

    with SessionLocal() as db:
        row = db.get(KbEmbeddingConfig, SINGLETON_ID)
        if row is not None:
            return EmbeddingConfig(
                provider_profile_id=row.provider_profile_id,
                vendor="",
                model=row.model,
                dim=row.dim,
            )
    # env fallback (backwards compatible with the existing .env setup)
    return EmbeddingConfig(
        provider_profile_id=None,
        vendor=settings.kb_embedding_vendor,
        model=settings.kb_embedding_model,
        dim=settings.kb_embedding_dim,
    )


def get() -> EmbeddingConfig:
    global _cached
    with _lock:
        if _cached is None:
            _cached = _load()
        return _cached


def refresh() -> None:
    global _cached
    with _lock:
        _cached = None
