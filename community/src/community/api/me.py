"""`/me`:我的资料、密码、会话(设备)、提交、分享。"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from community.api.deps import Ctx, CurrentUser, Db
from community.api.views import KIND_PATHS, iso, me_user, share_summary, version_out
from community.db import utcnow
from community.errors import ApiError
from community.models import AuthSession, Blob, BlobOwner, Item, ItemVersion, Share, ShareVersion, User
from community.pagination import paginate
from community.security import check_password_shape, hash_password, normalize_handle, verify_password
from community.storage import IMAGE_TYPES
from community.tokens import revoke_all, revoke_session
from mosael_formats.i18n import current_locale

router = APIRouter(prefix="/me", tags=["me"])


class MePatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=200)
    handle: str | None = Field(default=None, max_length=64)
    #: 头像:一张上传过的图片的 sha256(见 /shares/uploads);传 null 清掉头像。
    avatar_sha256: str | None = Field(default="__unset__", max_length=64)
    agree_terms_version: str | None = Field(default=None, max_length=32)


class PasswordChange(BaseModel):
    current_password: str | None = Field(default=None, max_length=512)
    new_password: str = Field(max_length=512)


@router.get("")
def get_me(principal: CurrentUser, ctx: Ctx, db: Db) -> dict:
    return me_user(ctx, db, principal.user)


@router.patch("")
def patch_me(body: MePatch, principal: CurrentUser, ctx: Ctx, db: Db) -> dict:
    """昵称、头像随时改;handle 只能改一次。"""
    user = db.get(User, principal.user.id)
    assert user is not None
    if body.display_name is not None:
        name = body.display_name.strip()
        if not (1 <= len(name) <= 64):
            raise ApiError(422, "display_name_invalid")
        user.display_name = name
    if body.handle is not None:
        handle = normalize_handle(body.handle)
        if handle != user.handle:
            if user.handle_changed_at is not None:
                raise ApiError(409, "handle_change_used")
            if db.scalar(select(func.count()).select_from(User).where(User.handle == handle)):
                raise ApiError(409, "handle_taken")
            user.handle = handle
            user.handle_changed_at = utcnow()
    if body.avatar_sha256 != "__unset__":
        if body.avatar_sha256 is None:
            user.avatar_sha256 = None
        else:
            blob = db.get(Blob, body.avatar_sha256)
            owned = db.get(BlobOwner, (user.id, body.avatar_sha256))
            if blob is None or blob.status != "ready" or owned is None or blob.content_type not in IMAGE_TYPES:
                raise ApiError(422, "avatar_invalid")
            user.avatar_sha256 = blob.sha256
    if body.agree_terms_version is not None:
        if body.agree_terms_version != ctx.settings.terms_version:
            raise ApiError(400, "terms_outdated")
        user.terms_version = body.agree_terms_version
        user.terms_agreed_at = utcnow()
    user.updated_at = utcnow()
    db.commit()
    return me_user(ctx, db, user)


@router.post("/password", status_code=204)
def change_password(body: PasswordChange, principal: CurrentUser, db: Db) -> Response:
    """设 / 改密码。已经有密码的要先给当前密码;改完吊销这个人**别的**会话(当前这台留着)。"""
    user = db.get(User, principal.user.id)
    assert user is not None
    check_password_shape(body.new_password)
    if user.password_hash:
        if not body.current_password:
            raise ApiError(400, "password_required")
        if not verify_password(user.password_hash, body.current_password):
            raise ApiError(401, "invalid_credentials")
    user.password_hash = hash_password(body.new_password)
    revoke_all(db, user.id, "password_changed", except_session_id=principal.session_id)
    db.commit()
    return Response(status_code=204)


@router.get("/sessions")
def my_sessions(
    principal: CurrentUser,
    db: Db,
    cursor: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=50),
) -> dict:
    now = utcnow()
    stmt = select(AuthSession).where(
        AuthSession.user_id == principal.user.id,
        AuthSession.revoked_at.is_(None),
        AuthSession.expires_at > now,
    )
    rows, next_cursor = paginate(
        db, stmt, keys=[AuthSession.created_at, AuthSession.id], cursor=cursor, limit=limit,
        key_of=lambda row: [row.created_at, row.id],
    )
    return {
        "items": [
            {
                "id": row.id,
                "kind": row.kind,
                "device_name": row.device_name,
                "ip": row.ip,
                "user_agent": row.user_agent,
                "created_at": iso(row.created_at),
                "last_used_at": iso(row.last_used_at),
                "current": row.id == principal.session_id,
            }
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_my_session(session_id: str, principal: CurrentUser, db: Db) -> Response:
    session = db.get(AuthSession, session_id)
    if session is None or session.user_id != principal.user.id:
        raise ApiError(404, "session_not_found")
    revoke_session(db, session, "revoked_by_user")
    db.commit()
    return Response(status_code=204)


@router.get("/submissions")
def my_submissions(
    principal: CurrentUser,
    db: Db,
    cursor: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=50),
) -> dict:
    """我提交过的每一个版本,带审核状态。"""
    stmt = select(ItemVersion).where(ItemVersion.submitter_id == principal.user.id)
    rows, next_cursor = paginate(
        db, stmt, keys=[ItemVersion.created_at, ItemVersion.id], cursor=cursor, limit=limit,
        key_of=lambda row: [row.created_at, row.id],
    )
    items = {item.id: item for item in db.scalars(select(Item).where(Item.id.in_({row.item_id for row in rows})))}
    out = []
    for row in rows:
        item = items[row.item_id]
        out.append(
            {
                **version_out(row, include_review=True),
                "kind": item.kind,
                "slug": item.slug,
                "title": item.title,
                "path": f"/{KIND_PATHS[item.kind]}/{item.slug}",
                "hidden": item.hidden_at is not None,
            }
        )
    return {"items": out, "next_cursor": next_cursor}


@router.get("/shares")
def my_shares(
    principal: CurrentUser,
    ctx: Ctx,
    db: Db,
    cursor: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=50),
) -> dict:
    stmt = select(Share).where(Share.owner_id == principal.user.id, Share.revoked_at.is_(None))
    rows, next_cursor = paginate(
        db, stmt, keys=[Share.updated_at, Share.id], cursor=cursor, limit=limit,
        key_of=lambda row: [row.updated_at, row.id],
    )
    versions = {
        version.id: version
        for version in db.scalars(select(ShareVersion).where(ShareVersion.id.in_({row.current_version_id for row in rows})))
    }
    locale = current_locale()
    return {
        "items": [
            {**share_summary(ctx, db, row, principal.user, versions.get(row.current_version_id or ""), locale),
             "hidden": row.hidden_at is not None}
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


__all__ = ["router"]
