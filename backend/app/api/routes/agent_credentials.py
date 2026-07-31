"""sidecar 刷新 OAuth 凭据时的写回通道。

读取走的是回合帧(凭据和 base_url / api_key 一样,随 run_turn 一起发下去),所以这里只有写。
写必须经过后端:凭据存在库里,而 sidecar 是每轮一个的短命进程。

两个接口对应 pi 的 `CredentialStore.modify` 一次调用的两半 —— 先 acquire 拿到独占权与当前值,
在 sidecar 里完成刷新,再 commit 写回。**不能合并成一个 PUT**:那样两个并发的 sidecar 会各自
刷新一次,而订阅制的 refresh token 多是一次性的,后手会让先手刚存好的凭据当场作废(表现为
「刚登录就被登出」)。互斥的实现见 app.domain.provider_auth。

鉴权:普通会话身份即可,和工具通道同级。理由是信任边界本就在这里 —— 后端每一轮都把供应商
密钥直接发给 sidecar,能发起一轮对话的人本来就能用到这份凭据。作为补偿,这两个接口**只写不读
明文**:acquire 返回的凭据是给刷新用的,commit 只回版本号,任何响应都不包含可长期使用的额外
信息。写坏顶多让该档案需要重新登录,不构成越权。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession
from app.db.models import ProviderProfile
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


def _profile(db: DbSession, profile_id: str) -> ProviderProfile:
    profile = db.get(ProviderProfile, profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="供应商不存在")
    return profile


@router.post("/agent/provider-credentials/{profile_id}/acquire", response_model=LeaseOut)
def acquire_credential_lease(profile_id: str, db: DbSession, user: CurrentUser) -> LeaseOut:
    """取得该档案凭据的独占刷新权。等不到(另一次刷新还没结束)返回 409,调用方稍后重试。"""
    profile = _profile(db, profile_id)
    try:
        lease = acquire_lease(profile_id)
    except CredentialLeaseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return LeaseOut(lease=lease, credential=read_credential(profile), version=profile.credential_version or 0)


@router.post("/agent/provider-credentials/{profile_id}/commit", response_model=CommitOut)
def commit_credential_lease(profile_id: str, body: CommitIn, db: DbSession, user: CurrentUser) -> CommitOut:
    """持租约写回刷新结果并释放。租约已超时被顶替时返回 409 —— 此时写回会覆盖别人的新凭据。"""
    try:
        profile = commit_credential(db, profile_id, body.lease, body.credential)
    except CredentialLeaseError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    logger.info("provider %s oauth credential updated (v%s)", profile_id, profile.credential_version)
    return CommitOut(version=profile.credential_version or 0)


@router.post("/agent/provider-credentials/{profile_id}/release", status_code=204)
def release_credential_lease(profile_id: str, body: CommitIn, db: DbSession, user: CurrentUser) -> None:
    """刷新失败时主动放手,不必等 TTL 到期 —— 否则下一轮对话要白等半分钟。"""
    _profile(db, profile_id)
    release_lease(profile_id, body.lease)
