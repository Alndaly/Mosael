"""把用户的 Provider 连接与该连接的秘密状态装配成一次可执行连接。

`ProviderProfile` 保存稳定的端点与非密配置；`ProviderCredential` 保存 API Key、OAuth 令牌和动态目录。
两者归同一用户但生命周期不同。本 Module 只返回 `ResolvedConnection`，避免业务代码自行拼接。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ProviderCredential, ProviderProfile

# 叶子模块:预设是纯数据。从 providers 引会成环(它在顶层 import 本模块)。
from app.domain.provider_presets import provider_definition


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

    **免密钥的 vendor 例外**(今天只有本地 ComfyUI):它没有账号也没有 key,而"有没有一份带
    秘密的凭据"这个判据对它永远为假 —— 于是那条连接一次都用不了,界面上还挂着一行"未配置你的
    密钥",而它压根没有密钥可配。用户唯一的出路是随便敲几个字符骗过判据,那既不是配置也不是安全。
    """
    if profile is None or not profile.enabled:
        return None
    # 连接本身也归人；不能只靠“找不到这个人的凭据”间接隔离。ComfyUI 这类免密连接没有
    # ProviderCredential 行，少了这道判断就会让任何用户使用别人的本地端点。
    if user_id is not None and profile.owner_user_id != user_id:
        return None
    credential = pick(db, profile.id, user_id)
    if credential is None and not is_keyless(profile.vendor):
        return None
    if credential is None:
        return _keyless(profile)
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


def is_keyless(vendor: str) -> bool:
    """这家供应商**不需要任何凭据**吗 —— 今天只有本机 ComfyUI。

    由预设声明,不从"有没有 secret 字段"反推:那个推论对 openrouter / anthropic 这些
    `fields: []` 但确实收 key 的 vendor 是错的(它们的 key 走通用的「我的密钥」入口)。
    """
    definition = provider_definition(vendor)
    return bool(definition and definition.keyless)


def _keyless(profile: ProviderProfile) -> ResolvedConnection:
    """免密钥连接的解析结果 —— 除了没有钥匙,和正常那份一模一样。"""
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
