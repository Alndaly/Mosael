"""供应商预设:纯数据,不依赖任何东西。

**单独一个叶子模块**,因为它同时被两边读:`providers`(解析连接)和 `provider_credentials`
(判断这家要不要钥匙),而前者在顶层 import 后者 —— 预设留在 providers 里的话,后者反过来读它
就成环了(见 tests/test_import_layering)。

模块内部的一张表负责书写数据，模块外只暴露校验后的不可变 ``ProviderDefinition``。
加一家供应商仍然只需加一条，但业务代码不能再自行解释自由字典。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

#: `audio` 是**音频生成**(音乐、BGM、歌曲、音效、给视频配声),和 `tts`(念一段字)是两种能力 ——
#: 同一家常常两样都有(百炼、火山),而它们的模型、参数、价目都不相通(见 ADR 0022)。
KNOWN_CAPABILITY_IDS = ("chat", "image", "video", "audio", "tts", "podcast")
KNOWN_AUTH_TYPES = ("oauth", "api_key")
KNOWN_FIELD_STORAGES = ("api_key", "base_url", "default_model", "extra")


@dataclass(frozen=True)
class ProviderField:
    """One typed configuration input owned by a Provider definition."""

    key: str
    label: str
    storage: str = "extra"
    secret: bool = False
    required: bool = False
    default: str = ""
    hint: str = ""

    @classmethod
    def from_mapping(cls, vendor: str, value: Mapping[str, object]) -> ProviderField:
        key = str(value.get("key") or "").strip()
        label = str(value.get("label") or "").strip()
        storage = str(value.get("storage") or "extra").strip()
        if not key or not label:
            raise ValueError(f"Provider {vendor!r}: every field needs both key and label")
        if storage not in KNOWN_FIELD_STORAGES:
            raise ValueError(f"Provider {vendor!r}: field {key!r} uses unknown storage {storage!r}")
        return cls(
            key=key,
            label=label,
            storage=storage,
            secret=bool(value.get("secret", False)),
            required=bool(value.get("required", False)),
            default=str(value.get("default") or ""),
            hint=str(value.get("hint") or ""),
        )


@dataclass(frozen=True)
class ProviderDefinition:
    """Stable Provider metadata consumed by settings, credentials and runtime selection.

    Protocol implementations deliberately do not live here.  They are composed by
    ``app.ai.providers.registry`` so declaring a capability and implementing it remain
    separate, independently testable decisions.
    """

    vendor: str
    label: str
    capability_ids: tuple[str, ...] = ()
    base_url: str = ""
    default_model: str = ""
    capabilities: str = ""
    fields: tuple[ProviderField, ...] = ()
    auth_types: tuple[str, ...] = ("api_key",)
    pi_provider: str = ""
    health_path: str = ""

    @classmethod
    def from_mapping(cls, vendor: str, value: Mapping[str, object]) -> ProviderDefinition:
        vendor = vendor.strip()
        if not vendor:
            raise ValueError("Provider vendor must not be empty")
        capability_ids = tuple(str(item) for item in value.get("capability_ids", ()))
        unknown_capabilities = set(capability_ids) - set(KNOWN_CAPABILITY_IDS)
        if unknown_capabilities:
            raise ValueError(f"Provider {vendor!r} declares unknown capabilities {sorted(unknown_capabilities)!r}")
        auth_types = tuple(str(item) for item in value.get("auth", ())) or ("api_key",)
        unknown_auth = set(auth_types) - set(KNOWN_AUTH_TYPES)
        if unknown_auth:
            raise ValueError(f"Provider {vendor!r} declares unknown auth types {sorted(unknown_auth)!r}")

        raw_fields = value.get("fields", ())
        if not isinstance(raw_fields, (list, tuple)):
            raise ValueError(f"Provider {vendor!r}: fields must be a list")
        fields = tuple(
            ProviderField.from_mapping(vendor, field)
            for field in raw_fields
            if isinstance(field, Mapping)
        )
        if len(fields) != len(raw_fields):
            raise ValueError(f"Provider {vendor!r}: fields contains an invalid entry")
        field_keys = [field.key for field in fields]
        duplicates = sorted({key for key in field_keys if field_keys.count(key) > 1})
        if duplicates:
            raise ValueError(f"Provider {vendor!r} has duplicate fields {duplicates!r}")

        health_path = str(value.get("health_path") or "")
        if health_path and not health_path.startswith("/"):
            raise ValueError(f"Provider {vendor!r}: health_path must start with /")
        return cls(
            vendor=vendor,
            label=str(value.get("label") or vendor),
            capability_ids=capability_ids,
            base_url=str(value.get("base_url") or ""),
            default_model=str(value.get("default_model") or ""),
            capabilities=str(value.get("capabilities") or ""),
            fields=fields,
            auth_types=auth_types,
            pi_provider=str(value.get("pi_provider") or ""),
            health_path=health_path,
        )

    def field(self, key: str) -> ProviderField | None:
        return next((field for field in self.fields if field.key == key), None)

_VENDOR_PRESETS: dict[str, dict[str, Any]] = {
    "alibaba": {
        # 平台叫**百炼**,DashScope 是它的 API 名字。此前写作「阿里云 DashScope (qwen)」——
        # 那个 (qwen) 后缀会让人以为这条连接只能配通义千问,而同一把 Key 上挂着的还有万相
        # (图像 / 视频)和 qwen-tts(语音)。括号里留 DashScope 是因为控制台发的 Key 就叫这个名。
        "label": "阿里云百炼 (DashScope)",
        "base_url": "https://dashscope.aliyuncs.com",
        # 百炼同时提供对话与向量嵌入(compatible-mode 端点),此前只写了 image,于是同一把
        # DashScope Key 想配对话还得再建一个「OpenAI 兼容端点」档案 —— 而它明明就是这一家。
        "capabilities": "对话与向量嵌入(compatible-mode 端点)、图像生成(qwen-image)、视频生成(万相)、音乐与音效生成(Fun-Music、AudioGen,仅北京地域)、语音合成(qwen-tts)。同一把 DashScope Key。",
        "capability_ids": ["chat", "image", "video", "audio", "tts"],
        "fields": [
            {
                "key": "api_key",
                "label": "DashScope API Key",
                "storage": "api_key",
                "secret": True,
                "required": True,
            },
            {
                "key": "base_url",
                # 同一条连接横跨四种能力,字段名不能跟着用户当前所在的设置分区变化。
                # compatible-mode 是对话/向量直接使用的地址；图像、视频和语音 Adapter 会把它
                # 归一回百炼原生 API 根。叫「对话 Endpoint」会让视频页看起来配置错了供应商。
                "label": "百炼 API Endpoint",
                "storage": "base_url",
                "default": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "hint": "通常保持默认。对话与向量直接使用兼容模式地址；图像 / 视频 / 语音会自动归一为百炼原生 API 根。",
            },
            {
                "key": "default_model",
                "label": "初始模型(可选)",
                "storage": "default_model",
                "hint": "仅在创建连接时先加入一个模型；它不是默认模型，保存后请在模型列表中管理。",
            },
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
            {
                "key": "api_key",
                "label": "方舟 API Key",
                "storage": "api_key",
                "secret": True,
                "required": True,
            },
            {
                "key": "base_url",
                "label": "Seedance 2.x Endpoint",
                "storage": "base_url",
                "default": "https://ark.cn-beijing.volces.com/api/v3",
                "hint": "通常保持默认。Seedance 1.x 模型会自动使用 LAS Endpoint。",
            },
            {
                "key": "default_model",
                "label": "初始模型(可选)",
                "storage": "default_model",
                "hint": "仅在创建连接时先加入一个模型；它不是默认模型，保存后请在模型列表中管理。",
            },
        ],
    },
    "moonshot": {
        "label": "Kimi (Moonshot)",
        "base_url": "https://api.moonshot.cn/v1",
        "capabilities": "对话、长文本、视觉理解(不支持图像 / 视频生成)",
        "capability_ids": ["chat"],
        "fields": [
            {
                "key": "api_key",
                "label": "Moonshot API Key",
                "storage": "api_key",
                "secret": True,
                "required": True,
            },
            {
                "key": "base_url",
                "label": "Moonshot Endpoint",
                "storage": "base_url",
                "default": "https://api.moonshot.cn/v1",
            },
            {
                "key": "default_model",
                "label": "初始模型(可选)",
                "storage": "default_model",
                "hint": "仅在创建连接时先加入一个模型；它不是默认模型，保存后请在模型列表中管理。",
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
            {
                "key": "api_key",
                "label": "DeepSeek API Key",
                "storage": "api_key",
                "secret": True,
                "required": True,
            },
            {
                "key": "base_url",
                "label": "DeepSeek Endpoint",
                "storage": "base_url",
                "default": "https://api.deepseek.com",
            },
            {
                "key": "default_model",
                "label": "初始模型(可选)",
                "storage": "default_model",
                "hint": "仅在创建连接时先加入一个模型；它不是默认模型，保存后请在模型列表中管理。",
            },
        ],
    },
    "minimax": {
        "label": "MiniMax",
        "base_url": "https://api.minimaxi.com/v1",
        "capabilities": "对话/视觉理解、海螺(Hailuo)视频生成。图像与语音需等对应 Adapter 接入。",
        "capability_ids": ["chat", "video"],
        "fields": [
            {
                "key": "api_key",
                "label": "MiniMax API Key",
                "storage": "api_key",
                "secret": True,
                "required": True,
            },
            {
                "key": "base_url",
                "label": "MiniMax Endpoint",
                "storage": "base_url",
                "default": "https://api.minimaxi.com/v1",
            },
            {
                "key": "default_model",
                "label": "初始模型(可选)",
                "storage": "default_model",
                "hint": "仅在创建连接时先加入一个模型；它不是默认模型，保存后请在模型列表中管理。",
            },
        ],
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        # 语音合成也在这里:它的引擎 id 就是 vendor id,而拆出 openai-tts / openai-compatible-tts
        # 两个 vendor 的理由分别是"能力要分开"和"要填自定义 endpoint" —— 前者被供应商⇄模型重构
        # 消掉了(能力挂模型行),后者本来就有 base_url 字段可填。
        "capabilities": "对话、图像生成、语音合成、向量嵌入 —— 同一把 Key,自建兼容端点改 Endpoint 即可。",
        "capability_ids": ["chat", "image", "tts"],
        "fields": [
            {
                "key": "api_key",
                "label": "OpenAI API Key",
                "storage": "api_key",
                "secret": True,
                "required": True,
            },
            {
                "key": "base_url",
                "label": "OpenAI Endpoint",
                "storage": "base_url",
                "default": "https://api.openai.com/v1",
            },
            {
                "key": "default_model",
                "label": "初始模型(可选)",
                "storage": "default_model",
                "hint": "仅在创建连接时先加入一个模型；它不是默认模型，保存后请在模型列表中管理。",
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
            {
                "key": "ak",
                "label": "Access Key (AK)",
                "storage": "extra",
                "secret": True,
                "hint": "选填,用于拉取账号可用音色",
            },
            {
                "key": "sk",
                "label": "Secret Key (SK)",
                "storage": "extra",
                "secret": True,
                "hint": "选填,与 AK 配对",
            },
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
            {
                "key": "appid",
                "label": "App ID",
                "storage": "extra",
                "secret": False,
                "required": True,
                "hint": "语音技术控制台的 App ID",
            },
        ],
    },
    "volcano-music": {
        "label": "火山引擎 AI 音乐生成",
        "base_url": "https://open.volcengineapi.com",
        # 第四个火山配置,同样不能和前三个合并:音乐生成属于「音视频理解与处理」那个产品
        # (服务名 imagination),**只认账号级 AK/SK 签名** —— 方舟 Key、语音 Key、播客 Token 都不行。
        # 只对企业认证账号开放(文档 https://www.volcengine.com/docs/84992/1404661)。
        "capabilities": "人声歌曲与纯音乐 / BGM 生成(按秒后付费或资源包,需企业认证账号的 AK/SK)",
        "capability_ids": ["audio"],
        "fields": [
            {
                "key": "api_key",
                "label": "Access Key ID (AK)",
                "storage": "api_key",
                "secret": True,
                "required": True,
                "hint": "火山引擎账号的 AK(访问控制 → API 访问密钥),子账号需要「智能美化特效」权限。",
            },
            {
                "key": "sk",
                "label": "Secret Access Key (SK)",
                "storage": "extra",
                "secret": True,
                "required": True,
                "hint": "与 AK 配对的 SK。只用来给请求签名,不会发给对面。",
            },
        ],
    },
    "openai-compatible": {
        "label": "OpenAI 兼容端点",
        "base_url": "",
        "capabilities": "任意 OpenAI 兼容端点:对话、图像生成与向量嵌入。",
        "capability_ids": ["chat", "image"],
        "fields": [
            {
                "key": "api_key",
                "label": "Bearer Token / API Key",
                "storage": "api_key",
                "secret": True,
                "required": True,
            },
            {
                "key": "base_url",
                "label": "兼容 Endpoint",
                "storage": "base_url",
                "required": True,
            },
            {
                "key": "default_model",
                "label": "初始模型",
                "storage": "default_model",
                "required": True,
                "hint": "创建连接时至少加入一个模型；之后可在模型列表继续添加，能力默认值在页面顶部单独设置。",
            },
        ],
    },
    "google": {
        "label": "Google (Veo/Gemini)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "capabilities": "视频生成(Veo)与音乐生成(Lyria 3 / 3.5)。Gemini/Imagen/Embedding 待对应 Adapter 接入后再开放。",
        "capability_ids": ["video", "audio"],
        "fields": [
            {
                "key": "api_key",
                "label": "Google API Key",
                "storage": "api_key",
                "secret": True,
                "required": True,
            },
            {
                "key": "base_url",
                "label": "Generative Language Endpoint",
                "storage": "base_url",
                "default": "https://generativelanguage.googleapis.com/v1beta",
            },
            {
                "key": "default_model",
                "label": "初始模型(可选)",
                "storage": "default_model",
                "hint": "仅在创建连接时先加入一个模型；它不是默认模型，保存后请在模型列表中管理。",
            },
        ],
    },
    "evolink": {
        "label": "Evolink AI",
        "base_url": "https://api.evolink.ai/v1",
        "health_path": "/models",
        "capabilities": "统一图像/视频/音乐生成网关：Seedance、Kling、Veo、Hailuo、WAN、Sora、GPT Image、Gemini、Seedream、Suno 等共用一把 Key。",
        "capability_ids": ["image", "video", "audio"],
        "fields": [
            {
                "key": "api_key",
                "label": "Evolink API Key",
                "storage": "api_key",
                "secret": True,
                "required": True,
            },
            {
                "key": "base_url",
                "label": "Evolink Endpoint",
                "storage": "base_url",
                "default": "https://api.evolink.ai/v1",
                "hint": "通常保持默认；素材会自动上传到 Evolink Files API，生成结果会立即下载回本地素材库。",
            },
            {
                "key": "default_model",
                "label": "初始模型(可选)",
                "storage": "default_model",
                "hint": "仅在创建连接时先加入一个模型；保存后可从模型列表选择不同引擎。",
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
        "capabilities": "视频生成与音效生成(可灵 Kling:文生音效、视频生音效)",
        "capability_ids": ["video", "audio"],
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
            {
                "key": "base_url",
                "label": "Kling Endpoint",
                "storage": "base_url",
                "default": "https://api.klingai.com",
            },
            {
                "key": "default_model",
                "label": "初始模型(可选)",
                "storage": "default_model",
                "hint": "仅在创建连接时先加入一个模型；它不是默认模型，保存后请在模型列表中管理。",
            },
        ],
    },
}


_PROVIDER_DEFINITIONS = tuple(
    ProviderDefinition.from_mapping(vendor, preset) for vendor, preset in _VENDOR_PRESETS.items()
)
_PROVIDER_DEFINITIONS_BY_VENDOR = {definition.vendor: definition for definition in _PROVIDER_DEFINITIONS}


def provider_definitions() -> tuple[ProviderDefinition, ...]:
    """Return Provider definitions in their intentional UI order."""
    return _PROVIDER_DEFINITIONS


def provider_definition(vendor: str) -> ProviderDefinition | None:
    """Look up a known Provider without manufacturing metadata for unknown ids."""
    return _PROVIDER_DEFINITIONS_BY_VENDOR.get(vendor)
