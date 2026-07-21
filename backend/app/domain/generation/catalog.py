from __future__ import annotations

from sqlalchemy import delete, select
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
        "id": "openai-compatible:gpt-image-2:image",
        "provider": "openai-compatible",
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
        "id": "bytedance:doubao-seedance-2-0-260128:video",
        "provider": "bytedance",
        "kind": "video",
        "model": "doubao-seedance-2-0-260128",
        "capabilities": {
            "modes": ["text-to-video", "image-to-video"],
            "endpoint": "ark",
            "max_duration_seconds": 10,
            "supports_audio": True,
        },
    },
    {
        "id": "bytedance:doubao-seedance-2-0-fast-260128:video",
        "provider": "bytedance",
        "kind": "video",
        "model": "doubao-seedance-2-0-fast-260128",
        "capabilities": {
            "modes": ["text-to-video", "image-to-video"],
            "endpoint": "ark",
            "max_duration_seconds": 10,
            "supports_audio": True,
        },
    },
    {
        "id": "bytedance:doubao-seedance-2-0-mini-260615:video",
        "provider": "bytedance",
        "kind": "video",
        "model": "doubao-seedance-2-0-mini-260615",
        "capabilities": {
            "modes": ["text-to-video", "image-to-video"],
            "endpoint": "ark",
            "max_duration_seconds": 10,
            "supports_audio": True,
        },
    },
    {
        "id": "bytedance:doubao-seedance-1-5-pro-251215:video",
        "provider": "bytedance",
        "kind": "video",
        "model": "doubao-seedance-1-5-pro-251215",
        "capabilities": {
            "modes": ["text-to-video", "image-to-video"],
            "endpoint": "las",
            "max_duration_seconds": 10,
            "supports_audio": True,
        },
    },
    {
        "id": "bytedance:doubao-seedance-1-0-pro-250528:video",
        "provider": "bytedance",
        "kind": "video",
        "model": "doubao-seedance-1-0-pro-250528",
        "capabilities": {
            "modes": ["text-to-video", "image-to-video"],
            "endpoint": "las",
            "max_duration_seconds": 10,
            "supports_audio": False,
        },
    },
    {
        "id": "bytedance:doubao-seedance-1-0-pro-fast-251015:video",
        "provider": "bytedance",
        "kind": "video",
        "model": "doubao-seedance-1-0-pro-fast-251015",
        "capabilities": {
            "modes": ["text-to-video", "image-to-video"],
            "endpoint": "las",
            "max_duration_seconds": 10,
            "supports_audio": False,
        },
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

REMOVED_BUILTIN_MODEL_IDS = {
    "bytedance:seedance:video",
}


def ensure_builtin_generation_models(db: Session) -> None:
    db.execute(delete(GenerationModel).where(GenerationModel.id.in_(REMOVED_BUILTIN_MODEL_IDS)))
    existing = set(db.scalars(select(GenerationModel.id)))
    for item in BUILTIN_MODELS:
        if item["id"] in existing:
            continue
        db.add(GenerationModel(**item))
    db.commit()
