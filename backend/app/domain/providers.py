from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Credential, ProviderProfile

"""
Provider profile resolution. Profiles are the primary credential store
(multiple per vendor allowed); the legacy single-secret credentials table
remains a fallback so earlier setups keep working.
"""

VENDOR_PRESETS: dict[str, dict[str, str]] = {
    "alibaba": {"label": "阿里云 DashScope (qwen)", "base_url": "https://dashscope.aliyuncs.com"},
    "bytedance": {"label": "火山方舟 ARK (Seedance/Doubao)", "base_url": "https://ark.cn-beijing.volces.com/api/v3"},
    "moonshot": {
        "label": "Kimi (Moonshot)",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k-vision-preview",
    },
    "minimax": {
        "label": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1",
        "default_model": "MiniMax-VL-01",
    },
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "default_model": "gpt-image-2"},
    "openai-compatible": {"label": "OpenAI 兼容端点", "base_url": ""},
    "google": {"label": "Google (Veo/Gemini)", "base_url": ""},
    "kuaishou": {"label": "快手 (Kling)", "base_url": ""},
}


def resolve_profile(db: Session, vendor: str, profile_id: str | None = None) -> ProviderProfile | None:
    if profile_id:
        profile = db.get(ProviderProfile, profile_id)
        return profile if profile is not None and profile.enabled else None
    return db.scalar(
        select(ProviderProfile)
        .where(ProviderProfile.vendor == vendor, ProviderProfile.enabled.is_(True))
        .order_by(ProviderProfile.created_at)
        .limit(1)
    )


def resolve_secret(db: Session, vendor: str) -> str | None:
    """Profile key first; legacy credentials row as fallback."""
    profile = resolve_profile(db, vendor)
    if profile is not None:
        return profile.api_key
    legacy = db.get(Credential, vendor)
    return legacy.secret if legacy else None
