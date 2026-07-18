from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import ProviderDefault, ProviderProfile

"""每种能力的默认供应商解析(统一到 ProviderProfile)。
capability: chat / image / video(embedding 走 KbEmbeddingConfig)。"""

CAPABILITIES = ("chat", "image", "video")


def resolve_default(db: Session, capability: str) -> tuple[ProviderProfile | None, str]:
    """返回该能力默认的 (启用的 profile, model);未配置或供应商已停用返回 (None, model)。"""
    row = db.get(ProviderDefault, capability)
    if row is None:
        return None, ""
    profile = None
    if row.provider_profile_id:
        profile = db.get(ProviderProfile, row.provider_profile_id)
        if profile is not None and not profile.enabled:
            profile = None
    return profile, row.model
