"""画板分享(ADR 0026 第 5 节)。

上传走三步:`POST /shares/uploads`(每个缺的文件一个上传地址,已有的跳过)→ 逐个 PUT 文件本体 →
`POST /shares` 提交快照。文件按内容哈希去重;服务端核对哈希(本地存储在 PUT 时核对,S3 在提交快照时核对)。
快照不可变:同一张画板(同一主人、同一 `board_key`)再分享 = 同一个链接的新版本。撤回之后链接立即 410。
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Query, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from community.api.deps import Ctx, CurrentUser, Db, MaybeUser, Principal
from community.api.items import ReportIn, file_report
from community.api.views import iso, og_path, public_user, share_media, share_summary, share_url, users_by_id
from community.context import Context
from community.crypto import sign_payload, verify_payload
from community.db import utcnow
from community.errors import ApiError, human_size
from community.logs import log_event
from community.models import (
    BLOB_READY,
    VISIBILITIES,
    VISIBILITY_PUBLIC,
    VISIBILITY_UNLISTED,
    Blob,
    BlobOwner,
    Share,
    ShareVersion,
    ShareVersionBlob,
    User,
)
from community.og import render_og
from community.pagination import paginate
from community.storage import IMAGE_TYPES, MEDIA_TYPES, blob_key, service_upload_url
from community.submissions import sniff_image
from mosael_formats.board_snapshot import SHA256_RE, SnapshotError, validate_snapshot
from mosael_formats.i18n import current_locale

logger = logging.getLogger(__name__)
router = APIRouter(tags=["shares"])

BOARD_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
SLUG_ALPHABET = "abcdefghijkmnopqrstuvwxyz23456789"
MAX_FILES_PER_REQUEST = 500
#: 报错时列给调用方看的「支持哪些类型」。
ALLOWED_TYPES = ", ".join(MEDIA_TYPES)


class UploadFileIn(BaseModel):
    sha256: str = Field(max_length=64)
    size: int = Field(ge=1)
    content_type: str = Field(max_length=100)


class UploadsIn(BaseModel):
    files: list[UploadFileIn] = Field(max_length=MAX_FILES_PER_REQUEST)


class ShareIn(BaseModel):
    board_key: str = Field(max_length=64)
    title: str = Field(default="", max_length=200)
    visibility: str = VISIBILITY_UNLISTED
    snapshot: dict[str, Any]


class SharePatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    visibility: str | None = None


def _usage(db: Session, user_id: str) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(Blob.size), 0)).join(BlobOwner, BlobOwner.sha256 == Blob.sha256).where(BlobOwner.user_id == user_id)
        )
        or 0
    )


def _claim(db: Session, user_id: str, sha: str) -> None:
    if db.get(BlobOwner, (user_id, sha)) is None:
        db.add(BlobOwner(user_id=user_id, sha256=sha))


# ---------------- 第一步:要上传地址 ----------------


@router.post("/shares/uploads")
def request_uploads(body: UploadsIn, principal: CurrentUser, ctx: Ctx, db: Db) -> dict:
    settings = ctx.settings
    user = principal.user
    wanted: dict[str, UploadFileIn] = {}
    for one in body.files:
        if not SHA256_RE.match(one.sha256):
            raise ApiError(422, "blob_hash_invalid")
        if one.content_type not in MEDIA_TYPES:
            raise ApiError(422, "content_type_not_allowed", content_type=one.content_type, allowed=ALLOWED_TYPES)
        if one.size > settings.share_max_file_bytes:
            raise ApiError(413, "file_too_large", limit=human_size(settings.share_max_file_bytes))
        wanted.setdefault(one.sha256, one)
    owned = {row for row in db.scalars(select(BlobOwner.sha256).where(BlobOwner.user_id == user.id, BlobOwner.sha256.in_(set(wanted))))}
    new_bytes = sum(one.size for sha, one in wanted.items() if sha not in owned)
    if _usage(db, user.id) + new_bytes > settings.user_storage_quota_bytes:
        raise ApiError(413, "quota_exceeded", limit=human_size(settings.user_storage_quota_bytes))

    uploads: list[dict] = []
    skipped: list[str] = []
    for sha, one in wanted.items():
        blob = db.get(Blob, sha)
        if blob is not None and blob.status == BLOB_READY:
            _claim(db, user.id, sha)
            skipped.append(sha)
            continue
        if blob is None:
            blob = Blob(sha256=sha, size=one.size, content_type=one.content_type, storage_key=blob_key(sha, one.content_type))
            db.add(blob)
            db.flush()
        _claim(db, user.id, sha)
        direct = ctx.storage.presigned_put(blob.storage_key, content_type=blob.content_type, size=one.size)
        if direct is None:
            token = sign_payload(
                settings.secret_key or "dev",
                {"u": user.id, "s": sha, "n": one.size},
                settings.upload_url_ttl_seconds,
            )
            direct = {"url": service_upload_url(settings, sha, token), "headers": {"Content-Type": blob.content_type}}
        uploads.append({"sha256": sha, "method": "PUT", "expires_in": settings.upload_url_ttl_seconds, **direct})
    db.commit()
    return {"uploads": uploads, "skipped": skipped}


# ---------------- 第二步:PUT 文件本体(本地存储) ----------------


@router.put("/uploads/{sha256}", status_code=204)
async def put_upload(sha256: str, request: Request, ctx: Ctx, db: Db, t: str = Query(default="", max_length=2048)) -> Response:
    """本地存储的上传地址。签名里写着是谁、哪个哈希、多大;内容边收边算哈希,对不上就不落盘。"""
    claims = verify_payload(ctx.settings.secret_key or "dev", t)
    if claims is None or claims.get("s") != sha256 or not SHA256_RE.match(sha256):
        raise ApiError(403, "upload_token_invalid")
    declared = int(claims.get("n", 0))
    blob = db.get(Blob, sha256)
    if blob is None:
        raise ApiError(403, "upload_token_invalid")
    if blob.status == BLOB_READY:
        return Response(status_code=204)
    limit = min(declared, ctx.settings.share_max_file_bytes)
    digest = hashlib.sha256()
    received = 0
    handle = tempfile.NamedTemporaryFile(delete=False, prefix="community-upload-")
    temp = Path(handle.name)
    try:
        with handle:
            async for chunk in request.stream():
                received += len(chunk)
                if received > limit:
                    raise ApiError(400, "size_mismatch")
                digest.update(chunk)
                handle.write(chunk)
        if received != declared:
            raise ApiError(400, "size_mismatch")
        if digest.hexdigest() != sha256:
            log_event(logger, "upload hash mismatch", logging.WARNING, user_id=claims.get("u"))
            raise ApiError(400, "hash_mismatch")
        if blob.content_type in IMAGE_TYPES:
            with temp.open("rb") as head:
                if sniff_image(head.read(64)) is None:
                    raise ApiError(422, "content_type_not_allowed", content_type=blob.content_type, allowed=ALLOWED_TYPES)
        await run_in_threadpool(ctx.storage.put_file, blob.storage_key, temp, content_type=blob.content_type)
    finally:
        temp.unlink(missing_ok=True)
    blob.size = received
    blob.status = BLOB_READY
    blob.verified_at = utcnow()
    db.commit()
    return Response(status_code=204)


def _verify_remote(ctx: Context, blob: Blob) -> bool:
    """S3 直传的文件:提交快照时读回来算一遍哈希。对不上就删掉那份对象。"""
    digest = hashlib.sha256()
    size = 0
    try:
        for chunk in ctx.storage.iter_chunks(blob.storage_key):
            size += len(chunk)
            if size > ctx.settings.share_max_file_bytes:
                break
            digest.update(chunk)
    except Exception as exc:  # noqa: BLE001 - 对象不存在 / 读不出都算「没上传」
        log_event(logger, "remote blob unreadable", logging.INFO, error=type(exc).__name__)
        return False
    if digest.hexdigest() != blob.sha256 or size > ctx.settings.share_max_file_bytes:
        ctx.storage.delete(blob.storage_key)
        return False
    blob.size = size
    return True


# ---------------- 第三步:提交快照 ----------------


def _new_slug(db: Session) -> str:
    for _ in range(20):
        slug = "".join(secrets.choice(SLUG_ALPHABET) for _ in range(10))
        if db.scalar(select(func.count()).select_from(Share).where(Share.slug == slug)) == 0:
            return slug
    raise ApiError(500, "internal_error")  # pragma: no cover


@router.post("/shares", status_code=201)
def create_share(body: ShareIn, principal: CurrentUser, ctx: Ctx, db: Db) -> JSONResponse:
    settings = ctx.settings
    user = principal.user
    if not BOARD_KEY_RE.match(body.board_key):
        raise ApiError(422, "board_key_invalid")
    if body.visibility not in VISIBILITIES:
        raise ApiError(422, "visibility_invalid")
    try:
        summary = validate_snapshot(body.snapshot, max_items=settings.share_max_items)
    except SnapshotError as exc:
        raise ApiError.from_format(exc, code="invalid_snapshot") from exc

    total = 0
    for sha in sorted(summary.hashes):
        blob = db.get(Blob, sha)
        if blob is None or db.get(BlobOwner, (user.id, sha)) is None:
            raise ApiError(422, "unknown_blob", sha256=sha)
        if blob.status != BLOB_READY:
            if ctx.storage.uploads_through_service or not _verify_remote(ctx, blob):
                raise ApiError(422, "unknown_blob", sha256=sha)
            blob.status, blob.verified_at = BLOB_READY, utcnow()
        total += blob.size
    if total > settings.share_max_total_bytes:
        raise ApiError(413, "share_too_large", limit=human_size(settings.share_max_total_bytes))

    now = utcnow()
    share = db.scalars(select(Share).where(Share.owner_id == user.id, Share.board_key == body.board_key)).first()
    created = share is None
    if share is None:
        share = Share(slug=_new_slug(db), owner_id=user.id, board_key=body.board_key, created_at=now)
        db.add(share)
        db.flush()
    number = int(db.scalar(select(func.coalesce(func.max(ShareVersion.number), 0)).where(ShareVersion.share_id == share.id)) or 0) + 1
    version = ShareVersion(
        share_id=share.id,
        number=number,
        snapshot=body.snapshot,
        item_count=summary.item_count,
        total_bytes=total,
        created_at=now,
    )
    db.add(version)
    db.flush()
    for sha in summary.hashes:
        db.add(ShareVersionBlob(version_id=version.id, sha256=sha))
    share.title = body.title.strip()[:200]
    share.visibility = body.visibility
    share.current_version_id = version.id
    share.updated_at = now
    db.commit()
    log_event(logger, "board shared", share_id=share.id, version=number, user_id=user.id, items=summary.item_count)
    return JSONResponse(
        {"slug": share.slug, "url": share_url(ctx, share, current_locale()), "version": number},
        status_code=201 if created else 200,
    )


# ---------------- 看、改、撤回 ----------------


def _get_share(db: Session, slug: str, principal: Principal | None, *, owner_only: bool = False) -> Share:
    share = db.scalars(select(Share).where(Share.slug == slug)).first()
    if share is None:
        raise ApiError(404, "share_not_found")
    is_owner = principal is not None and principal.user.id == share.owner_id
    if owner_only and not is_owner:
        raise ApiError(403, "not_owner")
    if share.revoked_at is not None:
        raise ApiError(410, "share_revoked")
    if share.hidden_at is not None and not (is_owner or (principal is not None and principal.is_moderator)):
        raise ApiError(410, "share_removed")
    return share


@router.get("/shares")
def list_public_shares(
    ctx: Ctx,
    db: Db,
    author: str | None = Query(default=None, max_length=32),
    cursor: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=50),
) -> dict:
    """公开的画板(`public`)—— 作者主页和「画板」列表用。知道链接才能看的(`unlisted`)不在这里。"""
    stmt = select(Share).where(Share.visibility == VISIBILITY_PUBLIC, Share.revoked_at.is_(None), Share.hidden_at.is_(None))
    if author:
        stmt = stmt.where(Share.owner_id.in_(select(User.id).where(User.handle == author.strip().lower())))
    rows, next_cursor = paginate(
        db, stmt, keys=[Share.updated_at, Share.id], cursor=cursor, limit=limit, key_of=lambda row: [row.updated_at, row.id]
    )
    owners = users_by_id(db, (row.owner_id for row in rows))
    versions = {
        one.id: one for one in db.scalars(select(ShareVersion).where(ShareVersion.id.in_({row.current_version_id for row in rows})))
    }
    locale = current_locale()
    return {
        "items": [
            share_summary(ctx, db, row, owners[row.owner_id], versions.get(row.current_version_id or ""), locale) for row in rows
        ],
        "next_cursor": next_cursor,
    }


@router.get("/shares/{slug}")
def get_share(slug: str, principal: MaybeUser, ctx: Ctx, db: Db) -> JSONResponse:
    share = _get_share(db, slug, principal)
    version = db.get(ShareVersion, share.current_version_id) if share.current_version_id else None
    if version is None:
        raise ApiError(404, "share_not_found")
    owner = db.get(User, share.owner_id)
    assert owner is not None
    hashes = [row for row in db.scalars(select(ShareVersionBlob.sha256).where(ShareVersionBlob.version_id == version.id))]
    body = {
        "slug": share.slug,
        "title": share.title,
        "visibility": share.visibility,
        "version": version.number,
        "url": share_url(ctx, share, current_locale()),
        "owner": public_user(ctx, db, owner),
        "created_at": iso(share.created_at),
        "updated_at": iso(share.updated_at),
        "og_image_url": og_path(share),
        "snapshot": version.snapshot,
        "media": share_media(ctx, db, hashes),
    }
    # 不公开的画板不让搜索引擎收录;内容由查看页按严格 CSP 渲染(见官网)。
    headers = {"Cache-Control": "private, max-age=30"}
    if share.visibility != VISIBILITY_PUBLIC:
        headers["X-Robots-Tag"] = "noindex"
    return JSONResponse(body, headers=headers)


@router.patch("/shares/{slug}")
def patch_share(slug: str, body: SharePatch, principal: CurrentUser, ctx: Ctx, db: Db) -> dict:
    share = _get_share(db, slug, principal, owner_only=True)
    if body.visibility is not None:
        if body.visibility not in VISIBILITIES:
            raise ApiError(422, "visibility_invalid")
        share.visibility = body.visibility
    if body.title is not None:
        share.title = body.title.strip()[:200]
    share.updated_at = utcnow()
    db.commit()
    version = db.get(ShareVersion, share.current_version_id) if share.current_version_id else None
    return share_summary(ctx, db, share, principal.user, version, current_locale())


@router.delete("/shares/{slug}", status_code=204)
def revoke_share(slug: str, principal: CurrentUser, db: Db) -> Response:
    """撤回:链接立即 410。同一张画板再分享会得到一个新链接。"""
    share = _get_share(db, slug, principal, owner_only=True)
    share.revoked_at = utcnow()
    share.board_key = None
    db.commit()
    log_event(logger, "share revoked", share_id=share.id, user_id=principal.user.id)
    return Response(status_code=204)


@router.post("/shares/{slug}/report", status_code=201)
def report_share(slug: str, body: ReportIn, principal: CurrentUser, db: Db) -> dict:
    share = _get_share(db, slug, principal)
    return {"id": file_report(db, principal, "share", share.id, body).id}


@router.get("/shares/{slug}/og.png")
def og_image(slug: str, ctx: Ctx, db: Db) -> Response:
    """分享预览图。第一次请求时生成并存起来,之后直接给存好的那张。"""
    share = _get_share(db, slug, None)
    version = db.get(ShareVersion, share.current_version_id) if share.current_version_id else None
    if version is None:
        raise ApiError(404, "share_not_found")
    if version.og_key and ctx.storage.exists(version.og_key):
        data = ctx.storage.read_bytes(version.og_key)
    else:
        owner = db.get(User, share.owner_id)
        summary = validate_snapshot(version.snapshot, max_items=max(ctx.settings.share_max_items, version.item_count))
        loaders = []
        for ref in summary.images[:4]:
            blob = db.get(Blob, ref.thumb_sha256 or ref.sha256) or db.get(Blob, ref.sha256)
            if blob is not None and blob.status == BLOB_READY and blob.content_type in IMAGE_TYPES:
                loaders.append(lambda key=blob.storage_key: ctx.storage.read_bytes(key))
        data = render_og(
            title=share.title,
            author=f"@{owner.handle}" if owner else "",
            images=loaders,
            wordmark_path=ctx.settings.og_wordmark_path,
            font_path=ctx.settings.og_font_path,
        )
        key = f"og/{version.id}.png"
        ctx.storage.put_bytes(key, data, content_type="image/png")
        version.og_key = key
        db.commit()
    return Response(data, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


__all__ = ["router"]
