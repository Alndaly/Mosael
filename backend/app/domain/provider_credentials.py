"""把用户的 Provider 连接与该连接的秘密状态装配成一次可执行连接。

`ProviderProfile` 保存稳定的端点与非密配置；`ProviderCredential` 保存 API Key、OAuth 令牌和动态目录。
两者归同一用户但生命周期不同。本 Module 只返回 `ResolvedConnection`，避免业务代码自行拼接。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ProviderCredential, ProviderProfile



@dataclass(frozen=True)
class ResolvedConnection:
    """一条连接 + 这次该用谁的钥匙。

    读取方拿到的是这个,而不是 `ProviderProfile` —— 后者身上**已经没有** `api_key` 了。
    这不是风格问题:密钥列留在档案行上,就等于留着一条不经过本模块、读到别人钥匙的路;
    搬走之后漏改的读取点会当场 AttributeError,而不是悄悄读到不该读的东西。
    """

    id: str
    name: str
    vendor: str
    base_url: str
    auth_type: str
    enabled: bool
    api_key: str = ""
    oauth_credential: dict | None = None
    model_catalog: list | None = None
    credential_version: int = 0
    #: 连接自身的非密配置,叠上这把钥匙带的密字段(火山 ak/sk 之类)。
    extra: dict[str, Any] = field(default_factory=dict)
    #: 这把钥匙是谁的。
    owner_user_id: str | None = None


def get(db: Session, profile_id: str, user_id: str) -> ProviderCredential | None:
    return db.get(ProviderCredential, {"profile_id": profile_id, "owner_user_id": user_id})


def pick(db: Session, profile_id: str, user_id: str | None) -> ProviderCredential | None:
    """**他自己那把**,没有就没有。

    这里没有回退。曾经有过「部署管理员共享的那一把」作为兜底,删掉了:它没有界面,而且回退到
    别人的钥匙正是这张表要消灭的东西 —— 「我以为花的是自己的额度,其实花的是别人的钱」。
    """
    if not user_id:
        return None
    mine = get(db, profile_id, user_id)
    return mine if mine is not None and _has_secret(mine) else None


def _has_secret(credential: ProviderCredential) -> bool:
    """一行空凭据不算「我配过了」—— 空行只是"曾经填过又清掉",不该被当成配置过。"""
    return bool((credential.api_key or "").strip() or credential.oauth_credential or credential.secrets)


def resolve_connection(
    db: Session,
    profile: ProviderProfile | None,
    user_id: str | None,
) -> ResolvedConnection | None:
    """这条连接 + 这个人该用的钥匙。没有可用的钥匙就回 None(调用方报「请先配置」)。

    **插件连接例外**(ADR 0020):它的凭据在插件实例上,由插件运行时只注入给那个插件自己;
    "有没有一份带秘密的凭据"这个判据对它永远为假 —— 照判的话那条连接一次都用不了。
    """
    if profile is None or not profile.enabled:
        return None
    # 连接本身也归人；不能只靠“找不到这个人的凭据”间接隔离。插件连接没有
    # ProviderCredential 行，少了这道判断就会让任何用户使用别人的本地端点。
    if user_id is not None and profile.owner_user_id != user_id:
        return None
    credential = pick(db, profile.id, user_id)
    # **插件连接的钥匙在插件实例上**(ADR 0020):这条连接只是生成领域指向那个实例的把手,
    # 凭据、端点都由插件运行时只注入给那个插件自己。在这里要一把连接上的钥匙,等于要一把
    # 永远不会有的钥匙。
    if credential is None and not profile.plugin_instance_id:
        return None
    if credential is None:
        return _without_key(profile)
    extra = dict(profile.extra or {})
    extra.update(credential.secrets or {})
    return ResolvedConnection(
        id=profile.id,
        name=profile.name,
        vendor=profile.vendor,
        base_url=profile.base_url or "",
        auth_type=profile.auth_type,
        enabled=profile.enabled,
        api_key=credential.api_key or "",
        oauth_credential=credential.oauth_credential,
        model_catalog=credential.model_catalog,
        credential_version=credential.credential_version or 0,
        extra=extra,
        owner_user_id=credential.owner_user_id,
    )


def _without_key(profile: ProviderProfile) -> ResolvedConnection:
    """插件连接的解析结果:没有连接上的钥匙 —— 钥匙在插件实例上(见 resolve_connection)。"""
    return ResolvedConnection(
        id=profile.id,
        name=profile.name,
        vendor=profile.vendor,
        base_url=profile.base_url or "",
        auth_type=profile.auth_type,
        enabled=profile.enabled,
        extra=dict(profile.extra or {}),
        owner_user_id=profile.owner_user_id,
    )


def upsert(
    db: Session,
    profile_id: str,
    user_id: str,
    *,
    api_key: str | None = None,
    secrets: dict | None = None,
) -> ProviderCredential:
    """写我自己的那把。"""
    credential = get(db, profile_id, user_id)
    if credential is None:
        credential = ProviderCredential(profile_id=profile_id, owner_user_id=user_id)
        db.add(credential)
    if api_key is not None:
        credential.api_key = api_key
    if secrets is not None:
        credential.secrets = {**(credential.secrets or {}), **secrets}
    return credential


def forget(db: Session, profile_id: str, user_id: str) -> None:
    """撤回我自己的钥匙。**连接不动** —— 它不是我的。"""
    credential = get(db, profile_id, user_id)
    if credential is not None:
        db.delete(credential)


def key_hint(credential: ProviderCredential | None) -> str:
    """给界面看的尾四位。只对**自己的**那把生成 —— 别人的钥匙连尾数都不该露。"""
    if credential is None:
        return ""
    if credential.api_key:
        return f"…{credential.api_key[-4:]}"
    return "已登录" if credential.oauth_credential else ""
