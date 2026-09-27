"""管理(`moderator` 以上):审核队列、通过 / 驳回、下架、举报。"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from community.api.deps import Ctx, Db, Moderator
from community.api.views import KIND_PATHS, iso, public_user, users_by_id, version_out
from community.db import utcnow
from community.errors import ApiError
from community.logs import log_event
from community.models import (
    KIND_PLUGIN,
    KIND_WORKFLOW,
    REPORT_DISMISSED,
    REPORT_OPEN,
    REPORT_RESOLVED,
    VERSION_PENDING,
    Item,
    ItemVersion,
    Report,
    Share,
)
from community.pagination import paginate
from community.submissions import plugin_diff, previous_approved, review

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])

#: 路径里的 kind → 表里的 kind。复数是 URL 的写法,单数也认。
TARGET_KINDS = {
    "workflows": KIND_WORKFLOW,
    "workflow": KIND_WORKFLOW,
    "plugins": KIND_PLUGIN,
    "plugin": KIND_PLUGIN,
    "shares": "share",
    "share": "share",
}


class ReviewIn(BaseModel):
    note: str = Field(default="", max_length=5000)


class HideIn(BaseModel):
    hidden: bool = True
    reason: str = Field(default="", max_length=200)


@router.get("/queue")
def queue(
    moderator: Moderator,
    ctx: Ctx,
    db: Db,
    cursor: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=50),
) -> dict:
    """待审核的提交,旧的在前看不到 —— 按提交时间倒序,每条带与上一个通过版本的差异。"""
    stmt = select(ItemVersion).where(ItemVersion.status == VERSION_PENDING)
    rows, next_cursor = paginate(
        db, stmt, keys=[ItemVersion.created_at, ItemVersion.id], cursor=cursor, limit=limit,
        key_of=lambda row: [row.created_at, row.id],
    )
    items = {item.id: item for item in db.scalars(select(Item).where(Item.id.in_({row.item_id for row in rows})))}
    submitters = users_by_id(db, (row.submitter_id for row in rows))
    out = []
    for row in rows:
        item = items[row.item_id]
        meta = row.meta or {}
        entry = meta.get("index_entry") or {}
        out.append(
            {
                **version_out(row, include_review=True),
                "kind": item.kind,
                "item": {"slug": item.slug, "title": item.title, "plugin_id": item.plugin_id, "path": f"/{KIND_PATHS[item.kind]}/{item.slug}"},
                "submitter": public_user(ctx, db, submitters[row.submitter_id]),
                "manifest": meta.get("manifest"),
                "permissions": entry.get("permissions", []),
                "tools": entry.get("tools", []),
                "files": meta.get("files", []),
                "diff": plugin_diff(row, previous_approved(db, row)) if item.kind == KIND_PLUGIN else None,
            }
        )
    return {"items": out, "next_cursor": next_cursor}


def _review(version_id: str, moderator: Moderator, db: Db, body: ReviewIn, approve: bool) -> dict:
    version = db.get(ItemVersion, version_id)
    if version is None:
        raise ApiError(404, "item_not_found")
    review(db, version, moderator.user, approve=approve, note=body.note)
    db.commit()
    return version_out(version, include_review=True)


@router.post("/submissions/{version_id}/approve")
def approve(version_id: str, moderator: Moderator, db: Db, body: ReviewIn | None = None) -> dict:
    return _review(version_id, moderator, db, body or ReviewIn(), True)


@router.post("/submissions/{version_id}/reject")
def reject(version_id: str, moderator: Moderator, db: Db, body: ReviewIn | None = None) -> dict:
    return _review(version_id, moderator, db, body or ReviewIn(), False)


@router.post("/items/{kind}/{slug}/hide")
def hide(kind: str, slug: str, moderator: Moderator, db: Db, body: HideIn | None = None) -> dict:
    """下架(或 `{"hidden": false}` 重新上架)。下架的同时把指向它的未处理举报标成已处理。"""
    body = body or HideIn()
    target_kind = TARGET_KINDS.get(kind)
    if target_kind is None:
        raise ApiError(422, "kind_invalid")
    now = utcnow()
    if target_kind == "share":
        target = db.scalars(select(Share).where(Share.slug == slug)).first()
        if target is None:
            raise ApiError(404, "share_not_found")
    else:
        target = db.scalars(select(Item).where(Item.kind == target_kind, Item.slug == slug)).first()
        if target is None:
            raise ApiError(404, "item_not_found")
    target.hidden_at = now if body.hidden else None
    target.hidden_reason = body.reason if body.hidden else ""
    if body.hidden:
        db.execute(
            update(Report)
            .where(Report.target_id == target.id, Report.status == REPORT_OPEN)
            .values(status=REPORT_RESOLVED, resolved_by=moderator.user.id, resolved_at=now)
        )
    db.commit()
    log_event(logger, "moderation hide", kind=target_kind, target_id=target.id, hidden=body.hidden, moderator_id=moderator.user.id)
    return {"kind": target_kind, "slug": slug, "hidden": body.hidden}


def _report_target(db: Db, report: Report) -> dict:
    if report.target_kind == "share":
        share = db.get(Share, report.target_id)
        return {"kind": "share", "slug": share.slug if share else None, "title": share.title if share else None}
    item = db.get(Item, report.target_id)
    return {"kind": report.target_kind, "slug": item.slug if item else None, "title": item.title if item else None}


@router.get("/reports")
def reports(
    moderator: Moderator,
    ctx: Ctx,
    db: Db,
    status: str = Query(default=REPORT_OPEN, pattern="^(open|resolved|dismissed|all)$"),
    cursor: str | None = None,
    limit: int | None = Query(default=None, ge=1, le=50),
) -> dict:
    stmt = select(Report)
    if status != "all":
        stmt = stmt.where(Report.status == status)
    rows, next_cursor = paginate(
        db, stmt, keys=[Report.created_at, Report.id], cursor=cursor, limit=limit, key_of=lambda row: [row.created_at, row.id]
    )
    reporters = users_by_id(db, (row.reporter_id for row in rows))
    return {
        "items": [
            {
                "id": row.id,
                "target": _report_target(db, row),
                "reason": row.reason,
                "detail": row.detail,
                "status": row.status,
                "reporter": public_user(ctx, db, reporters[row.reporter_id]) if row.reporter_id in reporters else None,
                "created_at": iso(row.created_at),
                "resolved_at": iso(row.resolved_at),
            }
            for row in rows
        ],
        "next_cursor": next_cursor,
    }


@router.post("/reports/{report_id}/dismiss")
def dismiss_report(report_id: str, moderator: Moderator, db: Db) -> dict:
    report = db.get(Report, report_id)
    if report is None:
        raise ApiError(404, "not_found")
    report.status = REPORT_DISMISSED
    report.resolved_by = moderator.user.id
    report.resolved_at = utcnow()
    db.commit()
    return {"id": report.id, "status": report.status}


__all__ = ["router"]
