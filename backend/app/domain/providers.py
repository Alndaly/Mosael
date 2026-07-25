from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProviderProfile

"""
Provider adapter configuration.

Each vendor preset declares the exact fields its adapter needs. The database
still stores the resolved values in ProviderProfile columns/extra for now, but
the public contract is adapter config, not a generic "credential" shape.
"""

VENDOR_PRESETS: dict[str, dict[str, Any]] = {
    "alibaba": {
        "label": "阿里云 DashScope (qwen)",
        "base_url": "https://dashscope.aliyuncs.com",
        "capabilities": "图像生成(qwen-image)。对话/嵌入请用 OpenAI 兼容端点单独配置。",
        "capability_ids": ["image"],
        "fields": [
            {"key": "api_key", "label": "DashScope API Key", "storage": "api_key", "secret": True, "required": True},
            {
                "key": "base_url",
                "label": "图像生成 Endpoint",
                "storage": "base_url",
                "default": "https://dashscope.aliyuncs.com",
                "hint": "通常保持默认;自建代理或区域端点可在这里覆盖。",
            },
            {"key": "default_model", "label": "图像模型", "storage": "default_model", "default": "qwen-image"},
        ],
    },
    "bytedance": {
        "label": "火山 Seedance 视频生成",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "default_model": "doubao-seedance-2-0-260128",
        "capabilities": "视频生成(Seedance)。2.x 走 ARK;1.x 在默认端点下由 Adapter 切到 LAS。",
        "capability_ids": ["video"],
        "fields": [
            {"key": "api_key", "label": "方舟 API Key", "storage": "api_key", "secret": True, "required": True},
            {
                "key": "base_url",
                "label": "Seedance 2.x Endpoint",
                "storage": "base_url",
                "default": "https://ark.cn-beijing.volces.com/api/v3",
                "hint": "通常保持默认。Seedance 1.x 模型会自动使用 LAS Endpoint。",
            },
            {
                "key": "default_model",
                "label": "视频模型",
                "storage": "default_model",
                "default": "doubao-seedance-2-0-260128",
            },
        ],
    },
    # 与 "bytedance"(视频)刻意分开:同一把方舟 Key 也各配各的档案,
    # 一处改动不牵连另一处(openai-tts / volcano-podcast 同款先例)。
    "bytedance-image": {
        "label": "火山 Seedream 图像生成",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "default_model": "doubao-seedream-4-0-250828",
        "capabilities": "图像生成(Seedream)。4.x 支持参考图;3.x t2i 支持 seed。",
        "capability_ids": ["image"],
        "fields": [
            {"key": "api_key", "label": "方舟 API Key", "storage": "api_key", "secret": True, "required": True},
            {
                "key": "base_url",
                "label": "ARK Endpoint",
                "storage": "base_url",
                "default": "https://ark.cn-beijing.volces.com/api/v3",
                "hint": "通常保持默认。",
            },
            {
                "key": "default_model",
                "label": "图像模型",
                "storage": "default_model",
                "default": "doubao-seedream-4-0-250828",
            },
        ],
    },
    "moonshot": {
        "label": "Kimi (Moonshot)",
        "base_url": "https://api.moonshot.cn/v1",
        "default_model": "moonshot-v1-8k-vision-preview",
        "capabilities": "对话、长文本、视觉理解(不支持图像 / 视频生成)",
        "capability_ids": ["chat"],
        "fields": [
            {"key": "api_key", "label": "Moonshot API Key", "storage": "api_key", "secret": True, "required": True},
            {
                "key": "base_url",
                "label": "Moonshot Endpoint",
                "storage": "base_url",
                "default": "https://api.moonshot.cn/v1",
            },
            {
                "key": "default_model",
                "label": "对话模型",
                "storage": "default_model",
                "default": "moonshot-v1-8k-vision-preview",
            },
        ],
    },
    "minimax": {
        "label": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1",
        "default_model": "MiniMax-VL-01",
        "capabilities": "对话/视觉理解。图像、视频、语音能力需等对应 Adapter 接入后再开放。",
        "capability_ids": ["chat"],
        "fields": [
            {"key": "api_key", "label": "MiniMax API Key", "storage": "api_key", "secret": True, "required": True},
            {
                "key": "base_url",
                "label": "MiniMax Endpoint",
                "storage": "base_url",
                "default": "https://api.minimaxi.com/v1",
            },
            {"key": "default_model", "label": "对话模型", "storage": "default_model", "default": "MiniMax-VL-01"},
        ],
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-image-2",
        "capabilities": "对话、图像生成(gpt-image)、向量嵌入",
        "capability_ids": ["chat", "image", "embedding"],
        "fields": [
            {"key": "api_key", "label": "OpenAI API Key", "storage": "api_key", "secret": True, "required": True},
            {"key": "base_url", "label": "OpenAI Endpoint", "storage": "base_url", "default": "https://api.openai.com/v1"},
            {"key": "default_model", "label": "默认模型", "storage": "default_model", "default": "gpt-image-2"},
        ],
    },
    "openai-tts": {
        "label": "OpenAI 语音合成",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini-tts",
        "capabilities": "语音合成(/audio/speech,预置音色)",
        "capability_ids": ["tts"],
        "fields": [
            {"key": "api_key", "label": "OpenAI API Key", "storage": "api_key", "secret": True, "required": True},
            {"key": "base_url", "label": "OpenAI Endpoint", "storage": "base_url", "default": "https://api.openai.com/v1"},
            {
                "key": "default_model",
                "label": "语音模型",
                "storage": "default_model",
                "default": "gpt-4o-mini-tts",
            },
        ],
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
            {
                "key": "api_key",
                "label": "语音合成 API Key",
                "storage": "api_key",
                "secret": True,
                "required": True,
                "hint": "火山语音技术的大模型 TTS API Key。",
            },
            {"key": "ak", "label": "Access Key (AK)", "storage": "extra", "secret": True, "hint": "选填,用于拉取账号可用音色"},
            {"key": "sk", "label": "Secret Key (SK)", "storage": "extra", "secret": True, "hint": "选填,与 AK 配对"},
        ],
    },
    "volcano-podcast": {
        "label": "火山引擎播客(双人对话)",
        "base_url": "wss://openspeech.bytedance.com",
        # A third 火山 adapter config, again not interchangeable: the podcast WebSocket authenticates
        # with appid + access token, and rejects the v3 API Key outright.
        "capabilities": "播客式双人对话音频(WebSocket,配置是 appid + Access Token,不是方舟 API Key)",
        "capability_ids": ["podcast"],
        "fields": [
            {
                "key": "api_key",
                "label": "Access Token",
                "storage": "api_key",
                "secret": True,
                "required": True,
                "hint": "播客 WebSocket 使用的 Access Token,不是方舟 API Key。",
            },
            {"key": "appid", "label": "App ID", "storage": "extra", "secret": False, "required": True, "hint": "语音技术控制台的 App ID"},
        ],
    },
    "comfyui": {
        "label": "ComfyUI(本地)",
        "base_url": "http://127.0.0.1:8188",
        # 免密钥:本地(或局域网 GPU 机器)的 ComfyUI 实例。工作流模板是接缝——
        # 任意 ComfyUI 图经 {{prompt}} 等占位符适配成"提示词 → 图"契约;留空用内置
        # txt2img(checkpoint 从 /object_info 现场发现)。
        "capabilities": "图像与视频生成(本地 ComfyUI,免密钥;图像可开箱即用,视频需粘贴工作流模板)",
        "capability_ids": ["image", "video"],
        "fields": [
            {
                "key": "base_url",
                "label": "ComfyUI 地址",
                "storage": "base_url",
                "default": "http://127.0.0.1:8188",
                "hint": "本机默认 8188;填局域网地址即可用远程 GPU 机器",
            },
            {
                "key": "workflow_template",
                "label": "工作流模板(可选,API 格式 JSON)",
                "storage": "extra",
                "multiline": True,
                "hint": "ComfyUI 里「导出 (API)」后粘贴;支持 {{prompt}} {{negative}} {{seed}} {{width}} {{height}} {{steps}} 占位符。留空用内置文生图。",
            },
        ],
    },
    "openai-compatible": {
        "label": "OpenAI 兼容端点",
        "base_url": "",
        "capabilities": "OpenAI 兼容对话、图像生成与向量嵌入端点。不同能力的 base_url / 模型可用独立 profile 配置。",
        "capability_ids": ["chat", "image", "embedding"],
        "fields": [
            {"key": "api_key", "label": "Bearer Token / API Key", "storage": "api_key", "secret": True, "required": True},
            {"key": "base_url", "label": "兼容 Endpoint", "storage": "base_url", "required": True},
            {"key": "default_model", "label": "默认模型", "storage": "default_model", "required": True},
        ],
    },
    "openai-compatible-tts": {
        "label": "OpenAI 兼容语音端点",
        "base_url": "",
        "capabilities": "OpenAI 兼容语音合成(/audio/speech)。用于自定义 base_url、代理或第三方兼容服务。",
        "capability_ids": ["tts"],
        "fields": [
            {"key": "api_key", "label": "Bearer Token / API Key", "storage": "api_key", "secret": True, "required": True},
            {"key": "base_url", "label": "兼容语音 Endpoint", "storage": "base_url", "required": True},
            {
                "key": "default_model",
                "label": "语音模型",
                "storage": "default_model",
                "default": "gpt-4o-mini-tts",
                "required": True,
            },
        ],
    },
    "google": {
        "label": "Google (Veo/Gemini)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "default_model": "veo-3.1-generate-preview",
        "capabilities": "视频生成(Veo)。Gemini/Imagen/Embedding 待对应 Adapter 接入后再开放。",
        "capability_ids": ["video"],
        "fields": [
            {"key": "api_key", "label": "Google API Key", "storage": "api_key", "secret": True, "required": True},
            {
                "key": "base_url",
                "label": "Generative Language Endpoint",
                "storage": "base_url",
                "default": "https://generativelanguage.googleapis.com/v1beta",
            },
            {
                "key": "default_model",
                "label": "视频模型",
                "storage": "default_model",
                "default": "veo-3.1-generate-preview",
            },
        ],
    },
    "kuaishou": {
        "label": "快手 (Kling)",
        "base_url": "https://api.klingai.com",
        "default_model": "kling-v3",
        "capabilities": "视频与图像生成(可灵 Kling)",
        "capability_ids": ["video"],
        "fields": [
            {
                "key": "api_key",
                "label": "Access Key / Bearer Token",
                "storage": "api_key",
                "secret": True,
                "required": True,
            },
            {
                "key": "secret_key",
                "label": "Secret Key",
                "storage": "extra",
                "secret": True,
                "hint": "官方 Kling 使用 Access Key + Secret Key:上面的 API Key 填 Access Key。第三方兼容端点可只填 Bearer API Key。",
            },
            {"key": "base_url", "label": "Kling Endpoint", "storage": "base_url", "default": "https://api.klingai.com"},
            {"key": "default_model", "label": "视频模型", "storage": "default_model", "default": "kling-v3"},
        ],
    },
}


# 已知能力全集(建/改档案时校验覆盖值,过滤掉无意义的能力名)。
ALL_CAPABILITY_IDS = ("chat", "image", "video", "tts", "podcast", "embedding")


def capability_ids_for_vendor(vendor: str) -> list[str]:
    """Runnable capability ids exposed by one configured profile.

    This is the providers Module's capability Interface: the UI, defaults, and
    validation all ask here instead of re-reading a free-form capability string.
    """
    return list(VENDOR_PRESETS.get(vendor, {}).get("capability_ids", []))


def normalize_capability_ids(values: list[str] | None) -> list[str] | None:
    """把用户传入的能力覆盖收敛成"已知能力、去重保序"的列表;None 透传(表示沿用 vendor 默认)。"""
    if values is None:
        return None
    seen: list[str] = []
    for value in values:
        if value in ALL_CAPABILITY_IDS and value not in seen:
            seen.append(value)
    return seen


def effective_capability_ids(profile: "ProviderProfile") -> list[str]:
    """档案的实际生效能力:有档案级覆盖用覆盖,否则回落 vendor 预设。"""
    override = getattr(profile, "capability_ids", None)
    if override is not None:
        return normalize_capability_ids(override) or []
    return capability_ids_for_vendor(profile.vendor)


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
    """One adapter-specific extra field, or "" when unset.

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
