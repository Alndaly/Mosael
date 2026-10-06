"""Provider 预设与用户连接选择的统一领域入口。

数据库仍以 `ProviderProfile` 命名以保持迁移兼容；业务调用方通过本 Module 取得用户自己的连接，
再由 `provider_credentials` 装配该连接的秘密与 OAuth 状态。Adapter 不直接查询这些表。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProviderProfile
from app.domain.providers import credentials as provider_credentials
from app.domain.providers.presets import (  # noqa: F401 —— 两个 vendor 能力函数在 presets,这里照旧可取
    KNOWN_AUTH_TYPES,
    KNOWN_CAPABILITY_IDS,
    capability_ids_for_vendor,
    normalize_capability_ids,
    provider_definition,
    served_by_pi,
)
from app.domain.providers.credentials import ResolvedConnection

#: 已知鉴权方式。顺序即 UI 上的优先级(订阅制排前面,因为不需要用户去找 Key)。
AUTH_TYPES = KNOWN_AUTH_TYPES


def auth_types_for_vendor(vendor: str) -> list[str]:
    """该 vendor 支持的鉴权方式;没声明的一律是纯 API Key(现存的十几个都是)。"""
    definition = provider_definition(vendor)
    return list(definition.auth_types) if definition else ["api_key"]


def default_auth_type(vendor: str) -> str:
    return auth_types_for_vendor(vendor)[0]


def pi_provider_id(vendor: str) -> str:
    """该 vendor 对应的 pi 内置 Provider id;不由 pi 承载的返回空串(走自建的 OpenAI 兼容 provider)。

    有 id 的不只是订阅制:Google Gemini 的 API Key 连接同样由 pi 的原生 Provider 承载(见 presets.served_by_pi)。
    """
    definition = provider_definition(vendor)
    return definition.pi_provider if definition else ""


def normalize_auth_type(vendor: str, value: str | None) -> str:
    """把用户传入的鉴权方式收敛到该 vendor 真正支持的集合,非法值回落到默认。"""
    allowed = auth_types_for_vendor(vendor)
    return value if value in allowed else allowed[0]


# 已知能力全集(建/改档案时校验覆盖值,过滤掉无意义的能力名)。
ALL_CAPABILITY_IDS = KNOWN_CAPABILITY_IDS


def supports_capability(vendor: str, capability: str) -> bool:
    return capability in capability_ids_for_vendor(vendor)


def find_enabled_connection(
    db: Session,
    vendor: str,
    profile_id: str | None = None,
    *,
    owner_user_id: str | None = None,
) -> ProviderProfile | None:
    """查找启用的连接；给出用户时绝不跨用户回退。"""
    if profile_id:
        profile = db.get(ProviderProfile, profile_id)
        if profile is None or not profile.enabled:
            return None
        if vendor and profile.vendor != vendor:
            return None
        if owner_user_id is not None and profile.owner_user_id != owner_user_id:
            return None
        return profile
    stmt = select(ProviderProfile).where(
        ProviderProfile.vendor == vendor,
        ProviderProfile.enabled.is_(True),
    )
    if owner_user_id is not None:
        stmt = stmt.where(ProviderProfile.owner_user_id == owner_user_id)
    return db.scalars(stmt.order_by(ProviderProfile.created_at).limit(1)).first()


#: 连接名的上限(ProviderProfile.name 的列宽)。插件实例的名字可以更长。
_NAME_LIMIT = 120


def adopt_plugin_connection(
    db: Session,
    *,
    plugin_instance_id: str,
    owner_user_id: str,
    vendor: str,
    name: str,
    enabled: bool,
) -> ProviderProfile:
    """**一个提供生成能力的插件实例,就是一条连接**(ADR 0020)。建出或对齐它。

    生成领域的一切 —— 选择器、默认模型、生成历史、用量、画板、工作流 —— 都指向连接和模型行。
    给它们各自加一个「也可能是插件」的分支,是七八处漏一处就静默失效的分支;反过来让插件实例
    **有一条连接**,那些地方一行都不用改。

    这一行是把手,不是副本:端点、配置、凭据都在插件实例上,这里只有身份 —— 归谁、叫什么、
    开没开。所以它没有 base_url,也不收钥匙(见 provider_credentials.resolve_connection)。
    实例删掉时外键级联把它删掉。
    """
    profile = db.scalars(
        select(ProviderProfile).where(ProviderProfile.plugin_instance_id == plugin_instance_id)
    ).first()
    if profile is None:
        profile = ProviderProfile(
            plugin_instance_id=plugin_instance_id,
            owner_user_id=owner_user_id,
            name=name[:_NAME_LIMIT],
            vendor=vendor,
            base_url="",
            auth_type="api_key",
            extra={},
            enabled=enabled,
        )
        db.add(profile)
    else:
        profile.owner_user_id = owner_user_id
        profile.name = name[:_NAME_LIMIT]
        profile.vendor = vendor
        profile.enabled = enabled
    db.flush()
    return profile


def list_enabled_connections(
    db: Session,
    *,
    owner_user_id: str | None = None,
    auth_type: str | None = None,
) -> list[ProviderProfile]:
    """列出启用连接；owner 与鉴权方式在查询阶段过滤，调用方不再先看见别人的连接再补救。"""
    stmt = select(ProviderProfile).where(ProviderProfile.enabled.is_(True))
    if owner_user_id is not None:
        stmt = stmt.where(ProviderProfile.owner_user_id == owner_user_id)
    if auth_type is not None:
        stmt = stmt.where(ProviderProfile.auth_type == auth_type)
    return list(db.scalars(stmt.order_by(ProviderProfile.created_at)).all())


def resolve_connection(
    db: Session, vendor: str, profile_id: str | None = None, *, user_id: str | None
) -> ResolvedConnection | None:
    """一条归属当前用户的连接 + 该用户在这条连接上的凭据。

    `user_id` 是必填关键字而不是可选参数:每一处取供应商的地方都得回答「为谁取」。省掉这个问题
    的写法此前存在过 —— 结果是先选中别人的连接,再找不到自己的凭据,表现为明明配好了却不可用。
    """
    return provider_credentials.resolve_connection(
        db,
        find_enabled_connection(db, vendor, profile_id, owner_user_id=user_id),
        user_id,
    )
