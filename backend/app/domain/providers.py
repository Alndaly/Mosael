from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Credential, ProviderProfile

"""
Provider profile resolution. Profiles are the primary credential store
(multiple per vendor allowed); the legacy single-secret credentials table
remains a fallback so earlier setups keep working.
"""

VENDOR_PRESETS: dict[str, dict[str, Any]] = {
    "alibaba": {
        "label": "阿里云 DashScope (qwen)",
        "base_url": "https://dashscope.aliyuncs.com",
        "capabilities": "图像生成(qwen-image)。对话/嵌入请用 OpenAI 兼容端点单独配置。",
        "capability_ids": ["image"],
    },
    "bytedance": {
        "label": "火山方舟 ARK (Seedance/Doubao)",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "capabilities": "对话(Doubao / OpenAI 兼容)与视频生成(Seedance)。",
        "capability_ids": ["chat", "video"],
    },
    "moonshot": {
        "label": "Kimi (Moonshot)",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k-vision-preview",
        "capabilities": "对话、长文本、视觉理解(不支持图像 / 视频生成)",
        "capability_ids": ["chat"],
    },
    "minimax": {
        "label": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1",
        "default_model": "MiniMax-VL-01",
        "capabilities": "对话/视觉理解。图像、视频、语音能力需等对应 Adapter 接入后再开放。",
        "capability_ids": ["chat"],
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-image-2",
        "capabilities": "对话、图像生成(gpt-image)、向量嵌入",
        "capability_ids": ["chat", "image", "embedding"],
    },
    "volcano": {
        "label": "火山引擎语音合成(豆包 TTS)",
        "base_url": "https://openspeech.bytedance.com",
        # Deliberately separate from "bytedance": ARK and the speech service issue different
        # keys from different consoles, so one profile cannot serve both.
        "capabilities": "语音合成(大模型 TTS,需语音技术控制台的 API Key)",
        "capability_ids": ["tts"],
        # AK/SK are the account-level keys, and they only buy one thing here: pulling the live
        # voice list. Synthesis works without them — the built-in list is the fallback — so they
        # are optional and say so.
        "fields": [
            {"key": "ak", "label": "Access Key (AK)", "secret": True, "hint": "选填,用于拉取账号可用音色"},
            {"key": "sk", "label": "Secret Key (SK)", "secret": True, "hint": "选填,与 AK 配对"},
        ],
    },
    "volcano-podcast": {
        "label": "火山引擎播客(双人对话)",
        "base_url": "wss://openspeech.bytedance.com",
        # A third 火山 credential, again not interchangeable: the podcast WebSocket authenticates
        # with appid + access token, and rejects the v3 API Key outright.
        "capabilities": "播客式双人对话音频(WebSocket,凭据是 appid + Access Token,不是 API Key)",
        "capability_ids": ["podcast"],
        "fields": [
            {"key": "appid", "label": "App ID", "secret": False, "hint": "语音技术控制台的 App ID"},
        ],
    },
    "openai-compatible": {
        "label": "OpenAI 兼容端点",
        "base_url": "",
        "capabilities": "OpenAI 兼容对话、图像生成与向量嵌入端点。不同能力的 base_url / 模型可用独立 profile 配置。",
        "capability_ids": ["chat", "image", "embedding"],
    },
    "google": {
        "label": "Google (Veo/Gemini)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "default_model": "veo-3.1-generate-preview",
        "capabilities": "视频生成(Veo)。Gemini/Imagen/Embedding 待对应 Adapter 接入后再开放。",
        "capability_ids": ["video"],
    },
    "kuaishou": {
        "label": "快手 (Kling)",
        "base_url": "https://api.klingai.com",
        "default_model": "kling-v3",
        "capabilities": "视频与图像生成(可灵 Kling)",
        "capability_ids": ["video"],
        "fields": [
            {
                "key": "secret_key",
                "label": "Secret Key",
                "secret": True,
                "hint": "官方 Kling 使用 Access Key + Secret Key:上面的 API Key 填 Access Key。第三方兼容端点可只填 Bearer API Key。",
            },
        ],
    },
}


def capability_ids_for_vendor(vendor: str) -> list[str]:
    """Runnable capability ids exposed by one configured profile.

    This is the providers Module's capability Interface: the UI, defaults, and
    validation all ask here instead of re-reading a free-form capability string.
    """
    return list(VENDOR_PRESETS.get(vendor, {}).get("capability_ids", []))


def supports_capability(vendor: str, capability: str) -> bool:
    return capability in capability_ids_for_vendor(vendor)


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


def profile_extra(db: Session, vendor: str, key: str) -> str:
    """One vendor-specific credential, or "" when unset.

    Callers treat "" as absent rather than raising: every extra field is either optional
    (火山 AK/SK) or checked by the feature that needs it, which can say what is missing far
    more usefully than a KeyError here.
    """
    profile = resolve_profile(db, vendor)
    if profile is None:
        return ""
    value = (profile.extra or {}).get(key)
    return str(value) if value else ""


def require_profile(
    db: Session, profile_id: str | None = None, *, error: type[Exception] = RuntimeError
) -> ProviderProfile:
    """指定 id 时要求该 profile 存在且启用;缺省回退最早启用的一个。

    供应商选取是 providers 领域的事——workflows / publish / agent 各自的调用方只提供
    要抛的领域错误类型,不再各自复制这段查询(此前同一逻辑存在三份)。
    """
    if profile_id:
        profile = db.get(ProviderProfile, str(profile_id))
        if profile is None or not profile.enabled:
            raise error("指定的供应商配置不存在或已停用")
        return profile
    profile = first_enabled_profile(db)
    if profile is None:
        raise error("没有可用的 AI 供应商,请先在设置里添加")
    return profile


def resolve_secret(db: Session, vendor: str) -> str | None:
    """Profile key first; legacy credentials row as fallback."""
    profile = resolve_profile(db, vendor)
    if profile is not None:
        return profile.api_key
    legacy = db.get(Credential, vendor)
    return legacy.secret if legacy else None
