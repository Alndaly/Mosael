"""sidecar 刷新 OAuth 凭据时的写回通道。

读取走的是回合帧(凭据和 base_url / api_key 一样,随 run_turn 一起发下去),所以这里只有写。
写必须经过后端:凭据存在库里,而 sidecar 是每轮一个的短命进程。

两个接口对应 pi 的 `CredentialStore.modify` 一次调用的两半 —— 先 acquire 拿到独占权与当前值,
在 sidecar 里完成刷新,再 commit 写回。**不能合并成一个 PUT**:那样两个并发的 sidecar 会各自
刷新一次,而订阅制的 refresh token 多是一次性的,后手会让先手刚存好的凭据当场作废(表现为
「刚登录就被登出」)。互斥的实现见 app.domain.provider_auth。

鉴权:每个人只碰**自己那把钥匙**(见 domain/provider_credentials)。此前这里认的是「能发起一轮
对话的人」,而凭据当时挂在档案行上、不属于任何人 —— 于是任何一个成员都能 acquire 到别人登录的
订阅账号的明文凭据。现在 acquire/commit 都按 (连接, 当前用户) 定位:读不到别人的,写坏也只坏
自己的,顶多是自己那条连接要重新登录。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.db.models import ProviderProfile
from app.domain import provider_credentials
from app.domain.provider_auth import (
    CredentialLeaseError,
    acquire_lease,
    commit_credential,
    read_credential,
    release_lease,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["agent-credentials"])


class LeaseOut(BaseModel):
    lease: str
    #: 当前存着的凭据(pi 的 Credential 原样);未登录为 None。
    credential: dict | None
    version: int


class CommitIn(BaseModel):
    lease: str
    #: 刷新后的凭据;None 表示删除(登出)。
    credential: dict | None = None


class CommitOut(BaseModel):
    version: int


def _require_owned_profile(db: DbSession, profile_id: str, user_id: str) -> ProviderProfile:
    profile = db.get(ProviderProfile, profile_id)
    if profile is None or profile.owner_user_id != user_id:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return profile


@router.post("/agent/provider-credentials/{profile_id}/acquire", response_model=LeaseOut)
def acquire_credential_lease(profile_id: str, db: DbSession, user: CurrentUser) -> LeaseOut:
    """取得该档案凭据的独占刷新权。等不到(另一次刷新还没结束)返回 409,调用方稍后重试。"""
    _require_owned_profile(db, profile_id, user.id)
    try:
        lease = acquire_lease(profile_id, user.id)
    except CredentialLeaseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    mine = provider_credentials.get(db, profile_id, user.id)
    return LeaseOut(
        lease=lease, credential=read_credential(mine), version=(mine.credential_version if mine else 0) or 0
    )


@router.post("/agent/provider-credentials/{profile_id}/commit", response_model=CommitOut)
def commit_credential_lease(profile_id: str, body: CommitIn, db: DbSession, user: CurrentUser) -> CommitOut:
    """持租约写回刷新结果并释放。租约已超时被顶替时返回 409 —— 此时写回会覆盖别人的新凭据。"""
    _require_owned_profile(db, profile_id, user.id)
    try:
        row = commit_credential(db, profile_id, user.id, body.lease, body.credential)
    except CredentialLeaseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.info("provider %s oauth credential updated (v%s)", profile_id, row.credential_version)
    return CommitOut(version=row.credential_version or 0)


@router.post("/agent/provider-credentials/{profile_id}/release", status_code=204)
def release_credential_lease(profile_id: str, body: CommitIn, db: DbSession, user: CurrentUser) -> None:
    """刷新失败时主动放手,不必等 TTL 到期 —— 否则下一轮对话要白等半分钟。"""
    _require_owned_profile(db, profile_id, user.id)
    release_lease(profile_id, user.id, body.lease)
