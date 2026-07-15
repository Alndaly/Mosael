from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GenerationModel


BUILTIN_MODELS = [
    {
        "id": "openai:gpt-image-2:image",
        "provider": "openai",
        "kind": "image",
        "model": "gpt-image-2",
        "capabilities": {"modes": ["text-to-image", "image-to-image"], "max_prompt_chars": 8000},
    },
    {
        "id": "alibaba:qwen-image:image",
        "provider": "alibaba",
        "kind": "image",
        "model": "qwen-image",
        "capabilities": {"modes": ["text-to-image", "image-to-image"], "max_prompt_chars": 8000},
    },
    {
        "id": "bytedance:seedance:video",
        "provider": "bytedance",
        "kind": "video",
        "model": "seedance",
        "capabilities": {"modes": ["text-to-video", "image-to-video"], "max_duration_seconds": 10},
    },
    {
        "id": "google:veo:video",
        "provider": "google",
        "kind": "video",
        "model": "veo",
        "capabilities": {"modes": ["text-to-video", "image-to-video"], "max_duration_seconds": 8},
    },
    {
        "id": "kuaishou:kling:video",
        "provider": "kuaishou",
        "kind": "video",
        "model": "kling",
        "capabilities": {"modes": ["text-to-video", "image-to-video"], "max_duration_seconds": 10},
    },
]


def ensure_builtin_generation_models(db: Session) -> None:
    existing = set(db.scalars(select(GenerationModel.id)))
    for item in BUILTIN_MODELS:
        if item["id"] in existing:
            continue
        db.add(GenerationModel(**item))
    db.commit()
