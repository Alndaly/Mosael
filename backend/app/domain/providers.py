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
    "alibaba": {
        "label": "阿里云 DashScope (qwen)",
        "base_url": "https://dashscope.aliyuncs.com",
        "capabilities": "对话、图像与视频生成、向量嵌入(通义千问 / 万相)",
    },
    "bytedance": {
        "label": "火山方舟 ARK (Seedance/Doubao)",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "capabilities": "视频生成(Seedance)、对话与视觉(Doubao)、图像",
    },
    "moonshot": {
        "label": "Kimi (Moonshot)",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k-vision-preview",
        "capabilities": "对话、长文本、视觉理解(不支持图像 / 视频生成)",
    },
    "minimax": {
        "label": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1",
        "default_model": "MiniMax-VL-01",
        "capabilities": "对话、视频生成(海螺)、语音合成、图像",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-image-2",
        "capabilities": "对话、图像生成(gpt-image)、向量嵌入",
    },
    "volcano": {
        "label": "火山引擎语音合成(豆包 TTS)",
        "base_url": "https://openspeech.bytedance.com",
        # Deliberately separate from "bytedance": ARK and the speech service issue different
        # keys from different consoles, so one profile cannot serve both.
        "capabilities": "语音合成(大模型 TTS,需语音技术控制台的 API Key)",
    },
    "openai-compatible": {
        "label": "OpenAI 兼容端点",
        "base_url": "",
        "capabilities": "任意 OpenAI 兼容端点(本地 Ollama / vLLM / 第三方),能力随所接服务而定",
    },
    "google": {
        "label": "Google (Veo/Gemini)",
        "base_url": "",
        "capabilities": "对话(Gemini)、图像(Imagen)、视频(Veo)、向量嵌入",
    },
    "kuaishou": {
        "label": "快手 (Kling)",
        "base_url": "",
        "capabilities": "视频与图像生成(可灵 Kling)",
    },
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


def first_enabled_profile(db: Session) -> ProviderProfile | None:
    """第一个启用的供应商(任意 vendor),给 AI 助手对话用。"""
    return db.scalar(
        select(ProviderProfile).where(ProviderProfile.enabled.is_(True)).order_by(ProviderProfile.created_at).limit(1)
    )


def resolve_secret(db: Session, vendor: str) -> str | None:
    """Profile key first; legacy credentials row as fallback."""
    profile = resolve_profile(db, vendor)
    if profile is not None:
        return profile.api_key
    legacy = db.get(Credential, vendor)
    return legacy.secret if legacy else None
