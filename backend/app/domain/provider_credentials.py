from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProviderCredential, ProviderProfile, User

"""钥匙是人的,连接是部署的。

`ProviderProfile` 回答「怎么连到这家供应商」—— 端点、模型目录、定价规则,那是部署的配置。
`ProviderCredential` 回答「谁在花钱、以谁的身份调用」—— 那是某个人的身份。

压在一起的后果跑出来过:能发起一轮对话的人就能 acquire 到那份明文凭据;而普通成员又没法带
自己的钥匙,所有人共用部署管理员那一把 —— 订阅制账号被多人共用,供应商那边看到的是同一个账号。

**解析顺序:自己的 → 部署管理员共享的 → 没有。** 最后一档回 None 而不是回退到"随便找一把能用
的",因为"我以为用的是自己的额度,其实花的是别人的钱"是这里最坏的失败方式 —— 报「请先配置」
是能看懂的,悄悄用了别人的不是。
"""


@dataclass(frozen=True)
class ResolvedProvider:
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
    #: 这把钥匙是谁的。共享钥匙时是那位部署管理员。
    owner_user_id: str | None = None
    shared: bool = False


def get(db: Session, profile_id: str, user_id: str) -> ProviderCredential | None:
    return db.get(ProviderCredential, {"profile_id": profile_id, "owner_user_id": user_id})


def shared_credential(db: Session, profile_id: str) -> ProviderCredential | None:
    """部署管理员放的那把「大家都能用」的。"""
    return db.scalar(
        select(ProviderCredential)
        .join(User, User.id == ProviderCredential.owner_user_id)
        .where(
            ProviderCredential.profile_id == profile_id,
            ProviderCredential.shared.is_(True),
            User.is_deployment_admin.is_(True),
        )
        .order_by(ProviderCredential.created_at)
        .limit(1)
    )


def pick(db: Session, profile_id: str, user_id: str | None) -> ProviderCredential | None:
    """自己的 → 部署管理员共享的 → None。"""
    if user_id:
        mine = get(db, profile_id, user_id)
        if mine is not None and _has_secret(mine):
            return mine
    return shared_credential(db, profile_id)


def _has_secret(credential: ProviderCredential) -> bool:
    """一行空凭据不算「我配过了」—— 否则删掉钥匙之后会卡在自己那把空的上,永远够不到共享的。"""
    return bool((credential.api_key or "").strip() or credential.oauth_credential or credential.secrets)


def resolve(db: Session, profile: ProviderProfile | None, user_id: str | None) -> ResolvedProvider | None:
    """这条连接 + 这个人该用的钥匙。没有可用的钥匙就回 None(调用方报「请先配置」)。"""
    if profile is None or not profile.enabled:
        return None
    credential = pick(db, profile.id, user_id)
    if credential is None:
        return None
    extra = dict(profile.extra or {})
    extra.update(credential.secrets or {})
    return ResolvedProvider(
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
        shared=bool(credential.shared),
    )


def upsert(
    db: Session,
    profile_id: str,
    user_id: str,
    *,
    api_key: str | None = None,
    secrets: dict | None = None,
    shared: bool | None = None,
) -> ProviderCredential:
    """写我自己的那把。`shared` 的授权由路由层把关(只有部署管理员能置位)。"""
    credential = get(db, profile_id, user_id)
    if credential is None:
        credential = ProviderCredential(profile_id=profile_id, owner_user_id=user_id)
        db.add(credential)
    if api_key is not None:
        credential.api_key = api_key
    if secrets is not None:
        credential.secrets = {**(credential.secrets or {}), **secrets}
    if shared is not None:
        credential.shared = shared
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
