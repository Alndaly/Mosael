from __future__ import annotations

from sqlalchemy import delete
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
        "id": "alibaba:qwen-image-2.0-pro:image",
        "provider": "alibaba",
        "kind": "image",
        "model": "qwen-image-2.0-pro",
        "capabilities": {"modes": ["text-to-image", "image-to-image"], "max_prompt_chars": 8000},
    },
    {
        "id": "alibaba:qwen-image-edit:image",
        "provider": "alibaba",
        "kind": "image",
        "model": "qwen-image-edit",
        "capabilities": {"modes": ["image-to-image"], "max_prompt_chars": 8000},
    },
    {
        "id": "alibaba:qwen-image:image",
        "provider": "alibaba",
        "kind": "image",
        "model": "qwen-image",
        "capabilities": {"modes": ["text-to-image"], "max_prompt_chars": 8000},
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
    for item in BUILTIN_MODELS:
        existing = db.get(GenerationModel, item["id"])
        if existing is None:
            db.add(GenerationModel(**item))
            continue
        existing.provider = item["provider"]
        existing.kind = item["kind"]
        existing.model = item["model"]
        existing.capabilities = item["capabilities"]
        existing.enabled = True
    db.commit()
