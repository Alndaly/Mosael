"""浏览器池:持久登录档案(BrowserProfile)的增删改查。

档案 = 可复用的持久身份(分区 + 代理),不再只服务发布。发布账号绑定的档案在列表里标注平台/账号
id(pool 页据此区分「发布账号」与通用档案)。删除受租约/绑定保护(见 domain/browser)。
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.domain import sharing
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import BrowserProfileCreate, BrowserProfileOut, BrowserProfileUpdate
from app.core.permissions import ensure_workspace_access
from app.db.models import BrowserProfile, PublishAccount, User
from app.domain import browser

router = APIRouter(tags=["browser-profiles"])


def _serialize(db, prof: BrowserProfile, user: User, shared: set[str]) -> BrowserProfileOut:
    """回档案 + 若被发布账号绑定则带上平台/账号 id(pool 页标注用)。"""
    account = db.scalar(select(PublishAccount).where(PublishAccount.profile_id == prof.id))
    return BrowserProfileOut(
        id=prof.id,
        workspace_id=prof.workspace_id,
        name=prof.name,
        partition=prof.partition,
        proxy=prof.proxy,
        enabled=prof.enabled,
        last_used_at=prof.last_used_at,
        created_at=prof.created_at,
        platform=account.platform if account else None,
        bound_account_id=account.id if account else None,
        binding_status=account.binding_status if account else None,
        last_checked_at=account.last_checked_at if account else None,
        last_error=account.last_error if account else None,
        is_mine=prof.owner_user_id == user.id,
        shared=prof.id in shared,
    )


@router.get("/browser/profiles", response_model=list[BrowserProfileOut])
def list_profiles(workspace_id: str, db: DbSession, user: CurrentUser) -> list[BrowserProfileOut]:
    ensure_workspace_access(db, user, workspace_id)
    # 档案存的是**某人已登录的浏览器** —— 默认只有主人看得见(见 domain/sharing)。
    shared = sharing.shared_ids(db, "browser_profile", workspace_id)
    return [
        _serialize(db, prof, user, shared)
        for prof in browser.list_profiles(db, workspace_id)
        if sharing.may_use(db, "browser_profile", prof, user)
    ]


@router.post("/browser/profiles", response_model=BrowserProfileOut)
def create_profile(body: BrowserProfileCreate, db: DbSession, user: CurrentUser) -> BrowserProfileOut:
    ensure_workspace_access(db, user, body.workspace_id)
    prof = browser.create_profile(db, workspace_id=body.workspace_id, name=body.name, owner=user, proxy=body.proxy)
    db.commit()
    return _serialize(db, prof, user, sharing.shared_ids(db, "browser_profile", body.workspace_id))


@router.patch("/browser/profiles/{profile_id}", response_model=BrowserProfileOut)
def update_profile(
    profile_id: str, body: BrowserProfileUpdate, db: DbSession, user: CurrentUser
) -> BrowserProfileOut:
    prof = db.get(BrowserProfile, profile_id)
    if prof is None:
        raise HTTPException(status_code=404, detail="浏览器档案不存在")
    ensure_workspace_access(db, user, prof.workspace_id)
    fields = body.model_fields_set
    try:
        prof = browser.update_profile(
            db,
            prof.workspace_id,
            profile_id,
            name=body.name if "name" in fields else None,
            proxy=body.proxy if "proxy" in fields else browser._UNSET,
            enabled=body.enabled if "enabled" in fields else None,
        )
    except browser.BrowserDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _serialize(db, prof, user, sharing.shared_ids(db, "browser_profile", prof.workspace_id))


@router.delete("/browser/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: str, db: DbSession, user: CurrentUser) -> Response:
    prof = db.get(BrowserProfile, profile_id)
    if prof is None:
        raise HTTPException(status_code=404, detail="浏览器档案不存在")
    ensure_workspace_access(db, user, prof.workspace_id)
    try:
        browser.delete_profile(db, prof.workspace_id, profile_id)
    except browser.BrowserDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(status_code=204)
