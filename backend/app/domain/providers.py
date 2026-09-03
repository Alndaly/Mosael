"""Provider 预设与用户连接选择的统一领域入口。

数据库仍以 `ProviderProfile` 命名以保持迁移兼容；业务调用方通过本 Module 取得用户自己的连接，
再由 `provider_credentials` 装配该连接的秘密与 OAuth 状态。Adapter 不直接查询这些表。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProviderProfile
from app.domain import provider_credentials
from app.domain.provider_presets import (
    KNOWN_AUTH_TYPES,
    KNOWN_CAPABILITY_IDS,
    provider_definition,
)
from app.domain.provider_credentials import ResolvedConnection

#: 已知鉴权方式。顺序即 UI 上的优先级(订阅制排前面,因为不需要用户去找 Key)。
AUTH_TYPES = KNOWN_AUTH_TYPES


def auth_types_for_vendor(vendor: str) -> list[str]:
    """该 vendor 支持的鉴权方式;没声明的一律是纯 API Key(现存的十几个都是)。"""
    definition = provider_definition(vendor)
    return list(definition.auth_types) if definition else ["api_key"]


def default_auth_type(vendor: str) -> str:
    return auth_types_for_vendor(vendor)[0]


def pi_provider_id(vendor: str) -> str:
    """该 vendor 对应的 pi 内置 Provider id;非订阅制的返回空串(走自建的 OpenAI 兼容 provider)。"""
    definition = provider_definition(vendor)
    return definition.pi_provider if definition else ""


def normalize_auth_type(vendor: str, value: str | None) -> str:
    """把用户传入的鉴权方式收敛到该 vendor 真正支持的集合,非法值回落到默认。"""
    allowed = auth_types_for_vendor(vendor)
    return value if value in allowed else allowed[0]


# 已知能力全集(建/改档案时校验覆盖值,过滤掉无意义的能力名)。
ALL_CAPABILITY_IDS = KNOWN_CAPABILITY_IDS


def capability_ids_for_vendor(vendor: str) -> list[str]:
    """Runnable capability ids exposed by one configured profile.

    This is the providers Module's capability Interface: the UI, defaults, and
    validation all ask here instead of re-reading a free-form capability string.
    """
    definition = provider_definition(vendor)
    return list(definition.capability_ids) if definition else []


def normalize_capability_ids(values: list[str] | None) -> list[str] | None:
    """把用户传入的能力覆盖收敛成"已知能力、去重保序"的列表;None 透传(表示沿用 vendor 默认)。"""
    if values is None:
        return None
    seen: list[str] = []
    for value in values:
        if value in ALL_CAPABILITY_IDS and value not in seen:
            seen.append(value)
    return seen


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


def first_enabled_connection(
    db: Session,
    *,
    owner_user_id: str | None = None,
) -> ProviderProfile | None:
    """第一个启用的连接；给出用户时只在该用户的连接中选择。"""
    stmt = select(ProviderProfile).where(ProviderProfile.enabled.is_(True))
    if owner_user_id is not None:
        stmt = stmt.where(ProviderProfile.owner_user_id == owner_user_id)
    return db.scalars(stmt.order_by(ProviderProfile.created_at).limit(1)).first()


def require_connection(
    db: Session, profile_id: str | None = None, *, user_id: str | None, error: type[Exception] = RuntimeError
) -> ResolvedConnection:
    """指定 id 时要求该 profile 存在且启用;缺省回退最早启用的一个。

    供应商选取是 providers 领域的事——workflows / publish / agent 各自的调用方只提供
    要抛的领域错误类型,不再各自复制这段查询(此前同一逻辑存在三份)。
    """
    if profile_id:
        profile = db.get(ProviderProfile, str(profile_id))
        if profile is None or not profile.enabled or (user_id is not None and profile.owner_user_id != user_id):
            raise error("指定的供应商配置不存在或已停用")
    else:
        profile = first_enabled_connection(db, owner_user_id=user_id)
        if profile is None:
            raise error("没有可用的 AI 供应商连接,请先在设置里添加并配置")
    resolved = provider_credentials.resolve_connection(db, profile, user_id)
    if resolved is None:
        # 没有可用的钥匙时报出来,而不是找一把能用的顶上 —— 「我以为花的是自己的额度,
        # 其实花的是别人的钱」是这里最坏的失败方式。
        raise error(f"供应商「{profile.name}」还没有配置你的密钥,请先在设置里填写")
    return resolved
