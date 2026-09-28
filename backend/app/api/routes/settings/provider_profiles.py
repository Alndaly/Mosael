from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    ProviderCredentialIn,
    ProviderCredentialOut,
    ProviderHealthOut,
    ProviderProfileCreate,
    ProviderProfileOut,
    ProviderProfileUpdate,
    VendorFieldOut,
    VendorPresetOut,
)
from app.db.models import ProviderProfile
from app.domain import provider_auth, provider_connections, provider_credentials, provider_health
from app.domain.agent.host import mint_tool_token
from app.domain.permissions import require_own_profile
from app.domain.provider_presets import provider_definitions

router = APIRouter(tags=["settings"])


def profile_out(db: DbSession, profile: ProviderProfile, user: CurrentUser) -> ProviderProfileOut:
    """一条连接在**这个人**眼里的样子(钥匙状态说的是他自己那把,见 describe_connection)。"""
    return ProviderProfileOut.model_validate(profile).model_copy(
        update=provider_connections.describe_connection(db, profile, user.id)
    )


@router.get("/settings/provider-vendors", response_model=list[VendorPresetOut])
def list_vendor_presets(user: CurrentUser) -> list[VendorPresetOut]:
    return [
        VendorPresetOut(
            vendor=definition.vendor,
            label=definition.label,
            capability_ids=list(definition.capability_ids),
            base_url=definition.base_url,
            default_model=definition.default_model,
            capabilities=definition.capabilities,
            fields=[VendorFieldOut(**vars(field)) for field in definition.fields],
            auth=list(definition.auth_types),
        )
        for definition in provider_definitions()
    ]


@router.put("/settings/providers/{profile_id}/credential", response_model=ProviderCredentialOut)
def put_my_credential(
    profile_id: str, body: ProviderCredentialIn, db: DbSession, user: CurrentUser
) -> ProviderCredentialOut:
    """填**我自己**在这条连接上的钥匙。

    不要求部署管理员:连接与钥匙都归当前用户，只是端点配置和秘密/OAuth 状态分别保存、分别更新。
    """
    profile = require_own_profile(db, user, profile_id, editing=True)
    credential = provider_credentials.upsert(
        db,
        profile.id,
        user.id,
        api_key=(body.api_key or "").strip() if body.api_key is not None else None,
        secrets={k: v for k, v in (body.secrets or {}).items() if v.strip()} or None,
    )
    db.commit()
    db.refresh(credential)
    return ProviderCredentialOut(
        profile_id=profile.id,
        key_hint=provider_credentials.key_hint(credential),
        is_mine=True,
    )


@router.delete("/settings/providers/{profile_id}/credential", status_code=204)
def delete_my_credential(profile_id: str, db: DbSession, user: CurrentUser) -> Response:
    """撤回我自己的钥匙。**连接不动** —— 它不是我的。"""
    require_own_profile(db, user, profile_id, editing=True)
    provider_credentials.forget(db, profile_id, user.id)
    db.commit()
    return Response(status_code=204)


@router.get("/settings/providers", response_model=list[ProviderProfileOut])
def list_provider_profiles(db: DbSession, user: CurrentUser) -> list[ProviderProfileOut]:
    # **只给他自己的**。连接归人(见 db.models.ProviderProfile):此前这里不做任何过滤,
    # 于是新账号一进设置页就看到八条别人建的连接,每条底下一行「未配置你的密钥」。
    profiles = db.scalars(
        select(ProviderProfile)
        .where(ProviderProfile.owner_user_id == user.id)
        .order_by(ProviderProfile.created_at)
    ).all()
    # 自动续期只碰**我自己**那把钥匙 —— 过期的是谁的,谁登录的时候才刷得动。
    provider_auth.refresh_expired_in_background(
        [(profile, provider_credentials.get(db, profile.id, user.id)) for profile in profiles],
        mint_token=lambda: mint_tool_token(db, user),
    )
    return [profile_out(db, profile, user) for profile in profiles]


@router.post("/settings/providers", response_model=ProviderProfileOut)
def create_provider_profile(body: ProviderProfileCreate, db: DbSession, user: CurrentUser) -> ProviderProfileOut:
    """建一条**我自己的**连接。

    不再要求部署管理员:这是他自己的连接、他自己的钥匙、他自己的账单。要管理员才建得了的年代,
    普通成员只能看着别人的连接干瞪眼 —— 看得见、用不了、也建不了自己的。
    """
    # 只能从**自己的**连接复制密钥 —— 否则这就是一条读到别人钥匙的路。
    source = require_own_profile(db, user, body.copy_credentials_from) if body.copy_credentials_from else None
    try:
        profile = provider_connections.create_connection(
            db,
            owner_user_id=user.id,
            name=body.name,
            vendor=body.vendor,
            auth_type=body.auth_type,
            config=dict(body.config or {}),
            copy_credentials_from=source,
        )
    except provider_connections.ConnectionConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(profile)
    return profile_out(db, profile, user)


@router.patch("/settings/providers/{profile_id}", response_model=ProviderProfileOut)
def update_provider_profile(
    profile_id: str, body: ProviderProfileUpdate, db: DbSession, user: CurrentUser
) -> ProviderProfileOut:
    profile = require_own_profile(db, user, profile_id, editing=True)
    try:
        provider_connections.update_connection(
            db,
            profile,
            user_id=user.id,
            name=body.name,
            enabled=body.enabled,
            auth_type=body.auth_type,
            config=dict(body.config or {}),
        )
    except provider_connections.ConnectionConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(profile)
    return profile_out(db, profile, user)


@router.get("/settings/providers/{profile_id}/health", response_model=ProviderHealthOut)
def probe_provider_health(profile_id: str, db: DbSession, user: CurrentUser) -> ProviderHealthOut:
    """探一次这条连接通不通、往返多久。

    **只在被问到时探**,不做后台轮询:探针会真的打到用户的端点上(本地 Ollama、云端 /models),
    定时轮询等于替用户持续产生请求 —— 而"它现在通不通"这个问题只在他看着这一页时才有意义。
    """
    profile = require_own_profile(db, user, profile_id)
    result = provider_health.probe(provider_credentials.resolve_or_keyless(db, profile, user.id))
    return ProviderHealthOut(
        supported=result.supported,
        online=result.online,
        latency_ms=result.latency_ms,
        detail=result.detail,
    )


@router.delete("/settings/providers/{profile_id}", status_code=204)
def delete_provider_profile(profile_id: str, db: DbSession, user: CurrentUser) -> Response:
    profile = require_own_profile(db, user, profile_id, editing=True)
    provider_connections.delete_connection(db, profile)
    db.commit()
    return Response(status_code=204)





