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

预设还声明**鉴权方式**(`auth`):
  - "api_key" —— 用户自己填的密钥,走本文件里描述的 base_url / fields;
  - "oauth"   —— 订阅计划(Claude Pro/Max、Kimi Code、ChatGPT Plus/Pro……),没有可填的密钥,
                 令牌由授权流程换取、会过期、刷新时还会轮换。

订阅制这一档带 `pi_provider`:sidecar 直接用 pi 现成的 Provider 定义(端点、模型目录、
上下文窗口、各家 OAuth 的设备码/PKCE 流程全在里面),这边**一个字段都不重描**。理由是各家
OAuth 的差异极大(Copilot 的 endpoint 随凭据变、Codex 用自己的 responses API),照抄一份进
Python 就等于把六家协议维护在我们这儿,上游一改就悄悄失效。这里只留 vendor id → pi provider id
这一张映射表。
"""

VENDOR_PRESETS: dict[str, dict[str, Any]] = {
    "alibaba": {
        "label": "阿里云 DashScope (qwen)",
        "base_url": "https://dashscope.aliyuncs.com",
        # 百炼同时提供对话与向量嵌入(compatible-mode 端点),此前只写了 image,于是同一把
        # DashScope Key 想配对话还得再建一个「OpenAI 兼容端点」档案 —— 而它明明就是这一家。
        "capabilities": "图像生成(qwen-image)、对话与向量嵌入(compatible-mode 端点)。",
        "capability_ids": ["chat", "image", "embedding"],
        "fields": [
            {"key": "api_key", "label": "DashScope API Key", "storage": "api_key", "secret": True, "required": True},
            {
                "key": "base_url",
                "label": "图像生成 Endpoint",
                "storage": "base_url",
                "default": "https://dashscope.aliyuncs.com",
                "hint": "通常保持默认;自建代理或区域端点可在这里覆盖。",
            },
            {"key": "default_model", "label": "首个模型(可选)", "storage": "default_model", "hint": "留空即可 —— 保存后在模型列表里从供应商目录直接挑,那份是实时拉的。"},
        ],
    },
    "bytedance": {
        "label": "火山方舟 ARK",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        # **一家就是一家**。图像(Seedream)和视频(Seedance)此前是两个 vendor,理由是
        # "一处改动不牵连另一处" —— 那在"一个档案只有一套能力、一个默认模型"的年代成立。
        # 供应商⇄模型重构之后一条连接能挂任意多个模型、各自带能力,拆分只剩代价:同一把方舟 Key
        # 要填两遍,设置页里一个账号占两行。
        "capabilities": "图像生成(Seedream)与视频生成(Seedance)。同一把方舟 Key。",
        "capability_ids": ["image", "video"],
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
                "label": "首个模型(可选)",
                "storage": "default_model",
                "hint": "留空即可 —— 保存后在模型列表里从方舟目录直接挑,那份是实时拉的。",
            },
        ],
    },
    "moonshot": {
        "label": "Kimi (Moonshot)",
        "base_url": "https://api.moonshot.cn/v1",
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
                "label": "首个模型(可选)",
                "storage": "default_model",
                "hint": "留空即可 —— 保存后在模型列表里从供应商目录直接挑,那份是实时拉的。",
               },
        ],
    },
    "deepseek": {
        "label": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        # **只做对话**。此前这类档案只能选「OpenAI 兼容端点」,而那个预设为了覆盖各种自建网关
        # 声明了 chat/image/embedding —— 模型行没显式设能力时会把三样全继承下来,于是 DeepSeek
        # 的对话模型会冒到「AI 绘图」的可选项里。给它自己的预设,能力就说得准了。
        "capabilities": "对话、推理(不支持图像 / 视频生成)",
        "capability_ids": ["chat"],
        "fields": [
            {"key": "api_key", "label": "DeepSeek API Key", "storage": "api_key", "secret": True, "required": True},
            {
                "key": "base_url",
                "label": "DeepSeek Endpoint",
                "storage": "base_url",
                "default": "https://api.deepseek.com",
            },
            {"key": "default_model", "label": "首个模型(可选)", "storage": "default_model", "hint": "留空即可 —— 保存后在模型列表里从供应商目录直接挑,那份是实时拉的。"},
        ],
    },
    "minimax": {
        "label": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1",
        "capabilities": "对话/视觉理解,以及海螺(Hailuo)视频生成。图像与语音需等对应 Adapter 接入。",
        "capability_ids": ["chat", "video"],
        "fields": [
            {"key": "api_key", "label": "MiniMax API Key", "storage": "api_key", "secret": True, "required": True},
            {
                "key": "base_url",
                "label": "MiniMax Endpoint",
                "storage": "base_url",
                "default": "https://api.minimaxi.com/v1",
            },
            {"key": "default_model", "label": "首个模型(可选)", "storage": "default_model", "hint": "留空即可 —— 保存后在模型列表里从供应商目录直接挑,那份是实时拉的。"},
        ],
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        # 语音合成也在这里:它的引擎 id 就是 vendor id,而拆出 openai-tts / openai-compatible-tts
        # 两个 vendor 的理由分别是"能力要分开"和"要填自定义 endpoint" —— 前者被供应商⇄模型重构
        # 消掉了(能力挂模型行),后者本来就有 base_url 字段可填。
        "capabilities": "对话、图像生成、语音合成、向量嵌入 —— 同一把 Key,自建兼容端点改 Endpoint 即可。",
        "capability_ids": ["chat", "image", "tts", "embedding"],
        "fields": [
            {"key": "api_key", "label": "OpenAI API Key", "storage": "api_key", "secret": True, "required": True},
            {"key": "base_url", "label": "OpenAI Endpoint", "storage": "base_url", "default": "https://api.openai.com/v1"},
            {"key": "default_model", "label": "首个模型(可选)", "storage": "default_model", "hint": "留空即可 —— 保存后在模型列表里从供应商目录直接挑,那份是实时拉的。"},
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
        # 探活走 /system_stats:ComfyUI 没有 /models,而这个接口无鉴权、必然存在、返回小。
        "health_path": "/system_stats",
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
        "capabilities": "任意 OpenAI 兼容端点:对话、图像生成与向量嵌入。",
        "capability_ids": ["chat", "image", "embedding"],
        "fields": [
            {"key": "api_key", "label": "Bearer Token / API Key", "storage": "api_key", "secret": True, "required": True},
            {"key": "base_url", "label": "兼容 Endpoint", "storage": "base_url", "required": True},
            {"key": "default_model", "label": "默认模型", "storage": "default_model", "required": True},
        ],
    },
    "google": {
        "label": "Google (Veo/Gemini)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
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
                "label": "首个模型(可选)",
                "storage": "default_model",
                "hint": "留空即可 —— 保存后在模型列表里从供应商目录直接挑,那份是实时拉的。",
               },
        ],
    },
    # ── 订阅计划(OAuth)────────────────────────────────────────────────────────
    # 这一组刻意只声明「是哪家 + 能力」:端点、模型目录、授权流程都取自 pi 的同名 Provider。
    # fields 为空是对的 —— 用户要做的是点「登录」,不是找一把 Key 粘进来。
    "anthropic": {
        "label": "Anthropic Claude(Pro/Max 订阅或 API Key)",
        "capabilities": "对话。可用 Claude Pro/Max 订阅登录,也可填 Anthropic API Key。",
        "capability_ids": ["chat"],
        "auth": ["oauth", "api_key"],
        "pi_provider": "anthropic",
        "fields": [],
    },
    "kimi-coding": {
        "label": "Kimi Code(订阅)",
        "capabilities": "对话。走 Kimi Code 订阅计划,设备码授权。",
        "capability_ids": ["chat"],
        "auth": ["oauth", "api_key"],
        "pi_provider": "kimi-coding",
        "fields": [],
    },
    "openai-codex": {
        "label": "OpenAI Codex(ChatGPT Plus/Pro 订阅)",
        "capabilities": "对话。用 ChatGPT 账号授权,不需要 API Key。",
        "capability_ids": ["chat"],
        "auth": ["oauth"],
        "pi_provider": "openai-codex",
        "fields": [],
    },
    "github-copilot": {
        "label": "GitHub Copilot",
        "capabilities": "对话。用 GitHub 账号授权,模型随订阅档位变化。",
        "capability_ids": ["chat"],
        "auth": ["oauth", "api_key"],
        "pi_provider": "github-copilot",
        "fields": [],
    },
    "xai": {
        "label": "xAI Grok(SuperGrok / X Premium 或 API Key)",
        "capabilities": "对话。",
        "capability_ids": ["chat"],
        "auth": ["oauth", "api_key"],
        "pi_provider": "xai",
        "fields": [],
    },
    "openrouter": {
        "label": "OpenRouter",
        "capabilities": "对话。一个账号聚合数百个模型;可 OAuth 授权,也可填 API Key。",
        "capability_ids": ["chat"],
        "auth": ["oauth", "api_key"],
        "pi_provider": "openrouter",
        "fields": [],
    },
    "kuaishou": {
        "label": "快手 (Kling)",
        "base_url": "https://api.klingai.com",
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
            {"key": "default_model", "label": "首个模型(可选)", "storage": "default_model", "hint": "留空即可 —— 保存后在模型列表里从供应商目录直接挑,那份是实时拉的。"},
        ],
    },
}


#: 已知鉴权方式。顺序即 UI 上的优先级(订阅制排前面,因为不需要用户去找 Key)。
AUTH_TYPES = ("oauth", "api_key")


def auth_types_for_vendor(vendor: str) -> list[str]:
    """该 vendor 支持的鉴权方式;没声明的一律是纯 API Key(现存的十几个都是)。"""
    declared = VENDOR_PRESETS.get(vendor, {}).get("auth")
    if not declared:
        return ["api_key"]
    return [value for value in declared if value in AUTH_TYPES] or ["api_key"]


def default_auth_type(vendor: str) -> str:
    return auth_types_for_vendor(vendor)[0]


def pi_provider_id(vendor: str) -> str:
    """该 vendor 对应的 pi 内置 Provider id;非订阅制的返回空串(走自建的 OpenAI 兼容 provider)。"""
    return str(VENDOR_PRESETS.get(vendor, {}).get("pi_provider", ""))


def normalize_auth_type(vendor: str, value: str | None) -> str:
    """把用户传入的鉴权方式收敛到该 vendor 真正支持的集合,非法值回落到默认。"""
    allowed = auth_types_for_vendor(vendor)
    return value if value in allowed else allowed[0]


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
