from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProviderProfile
from app.domain import provider_credentials
from app.domain.provider_presets import VENDOR_PRESETS as _PRESETS
from app.domain.provider_credentials import ResolvedProvider

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

#: 从叶子模块引进来(见 provider_presets);这里 re-export,调用方不必改。
VENDOR_PRESETS = _PRESETS


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
ALL_CAPABILITY_IDS = ("chat", "image", "video", "tts", "podcast")


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


def connection(db: Session, vendor: str, profile_id: str | None = None) -> ProviderProfile | None:
    """这条**连接**本身(端点、模型目录、定价)。不含任何钥匙 —— 钥匙按人取,见 resolve_profile。"""
    if profile_id:
        profile = db.get(ProviderProfile, profile_id)
        return profile if profile is not None and profile.enabled else None
    return db.scalar(
        select(ProviderProfile)
        .where(ProviderProfile.vendor == vendor, ProviderProfile.enabled.is_(True))
        .order_by(ProviderProfile.created_at)
        .limit(1)
    )


def resolve_profile(
    db: Session, vendor: str, profile_id: str | None = None, *, user_id: str | None
) -> ResolvedProvider | None:
    """一条连接 + **这个人**该用的钥匙(自己的 → 部署管理员共享的 → None)。

    `user_id` 是必填关键字而不是可选参数:每一处取供应商的地方都得回答「为谁取」。省掉这个问题
    的写法此前存在过 —— 结果是所有人共用同一把钥匙,而钥匙是谁的没人说得清。
    """
    return provider_credentials.resolve(db, connection(db, vendor, profile_id), user_id)


def first_enabled_connection(db: Session) -> ProviderProfile | None:
    """第一个启用的连接(任意 vendor),给 AI 助手对话用。"""
    return db.scalar(
        select(ProviderProfile).where(ProviderProfile.enabled.is_(True)).order_by(ProviderProfile.created_at).limit(1)
    )


def first_enabled_profile(db: Session, *, user_id: str | None) -> ResolvedProvider | None:
    return provider_credentials.resolve(db, first_enabled_connection(db), user_id)


def profile_extra(db: Session, vendor: str, key: str) -> str:
    """One adapter-specific extra field, or "" when unset.

    Callers treat "" as absent rather than raising: every extra field is either optional
    (火山 AK/SK) or checked by the feature that needs it, which can say what is missing far
    more usefully than a KeyError here.
    """
    profile = connection(db, vendor)
    if profile is None:
        return ""
    value = (profile.extra or {}).get(key)
    return str(value) if value else ""


def require_profile(
    db: Session, profile_id: str | None = None, *, user_id: str | None, error: type[Exception] = RuntimeError
) -> ResolvedProvider:
    """指定 id 时要求该 profile 存在且启用;缺省回退最早启用的一个。

    供应商选取是 providers 领域的事——workflows / publish / agent 各自的调用方只提供
    要抛的领域错误类型,不再各自复制这段查询(此前同一逻辑存在三份)。
    """
    if profile_id:
        profile = db.get(ProviderProfile, str(profile_id))
        if profile is None or not profile.enabled:
            raise error("指定的供应商配置不存在或已停用")
    else:
        profile = first_enabled_connection(db)
        if profile is None:
            raise error("没有可用的 AI 供应商,请先在设置里添加")
    resolved = provider_credentials.resolve(db, profile, user_id)
    if resolved is None:
        # 没有可用的钥匙时报出来,而不是找一把能用的顶上 —— 「我以为花的是自己的额度,
        # 其实花的是别人的钱」是这里最坏的失败方式。
        raise error(f"供应商「{profile.name}」还没有配置你的密钥,请先在设置里填写")
    return resolved
