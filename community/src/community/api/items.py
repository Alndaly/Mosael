"""`/workflows`、`/plugins`、`/assets`:列表、详情、版本、提交、下载、点赞、举报;`/plugins/index.json` 给应用读。

三种条目的形状相同(ADR:「插件:同工作流的形状,路径换成 /plugins」),所以同一个工厂各建一份路由;
只有「收到的东西怎么校验、提交后是什么状态」按种类不同(见 submissions.py)。资产收的不是一个文件,
而是一个分享包(JSON,参考图已经走三步上传),下载也直接回分享包和每张图的地址(ADR 0027 §4)。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from community.api.deps import Ctx, CurrentUser, Db, MaybeUser, Principal
from community.api.views import KIND_PATHS, download_path, item_summaries, item_summary, tags_by_item, version_out
from community.context import Context
from community.errors import ApiError, human_size
from community.models import (
    KIND_ASSET,
    KIND_PLUGIN,
    KIND_WORKFLOW,
    REPORT_OPEN,
    VERSION_APPROVED,
    Item,
    ItemTag,
    ItemVersion,
    Like,
    Report,
    User,
)
from community.pagination import paginate
from community.stats import bump, item_series
from community.submissions import Metadata, asset_media, parse_tags, submit_asset, submit_plugin, submit_workflow
from mosael_formats.i18n import current_locale
from mosael_formats.plugin_index import ENTRY_KEYS

SORTS = ("trending", "new", "downloads")
#: `likeness`:冒用肖像(资产里的真人人物被别人拿去用了)。
REPORT_REASONS = ("spam", "malware", "copyright", "inappropriate", "broken", "likeness", "other")
ASSET_KINDS = ("character", "location", "prop")


class ReportIn(BaseModel):
    reason: str = Field(max_length=64)
    detail: str = Field(default="", max_length=2000)


class AssetIn(BaseModel):
    """提交一个资产 / 它的新版本。`bundle` 是 mosael.asset/1;真人人物要带 `consent_kind`(self / authorized)。"""

    bundle: dict
    consent_kind: str | None = Field(default=None, max_length=16)
    title: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=1000)
    description: str | None = Field(default=None, max_length=40000)
    tags: list[str] | str | None = None
    changelog: str = Field(default="", max_length=10000)

    def metadata(self) -> Metadata:
        return Metadata(
            title=self.title, summary=self.summary, description=self.description,
            tags=parse_tags(self.tags), changelog=self.changelog,
        )


async def read_upload(upload: UploadFile | None, limit: int) -> bytes:
    """读上传的文件,多读一个字节判断有没有超限 —— 不把一个超大的文件整个读进内存再说它太大。"""
    if upload is None:
        raise ApiError(422, "file_required")
    data = await upload.read(limit + 1)
    if len(data) > limit:
        raise ApiError(413, "file_too_large", limit=human_size(limit))
    if not data:
        raise ApiError(422, "file_required")
    return data


async def read_optional(upload: UploadFile | None, limit: int) -> bytes | None:
    if upload is None or not upload.filename:
        return None
    return await read_upload(upload, limit)


def visible(item: Item, principal: Principal | None) -> bool:
    """公开:有已公开的版本且没被下架。作者本人和审核员总能看到。"""
    if principal is not None and (principal.user.id == item.owner_id or principal.is_moderator):
        return True
    return item.current_version_id is not None and item.hidden_at is None


def get_item(db: Session, kind: str, slug: str, principal: Principal | None) -> Item:
    item = db.scalars(select(Item).where(Item.kind == kind, Item.slug == slug)).first()
    if item is None:
        raise ApiError(404, "item_not_found")
    if not visible(item, principal):
        raise ApiError(404 if item.hidden_at is None else 410, "item_not_found" if item.hidden_at is None else "item_hidden")
    return item


def public_items(kind: str) -> Select:
    return select(Item).where(Item.kind == kind, Item.current_version_id.is_not(None), Item.hidden_at.is_(None))


def list_items(
    ctx: Context,
    db: Session,
    kind: str,
    *,
    q: str | None,
    tag: str | None,
    sort: str,
    author: str | None,
    official: bool | None,
    cursor: str | None,
    limit: int | None,
    asset_kind: str | None = None,
) -> dict:
    if sort not in SORTS:
        raise ApiError(422, "invalid_request", fields="sort")
    stmt = public_items(kind)
    if q:
        needle = q.strip().lower()[:100]
        stmt = stmt.where(Item.search_text.contains(needle, autoescape=True))
    if tag:
        stmt = stmt.where(Item.id.in_(select(ItemTag.item_id).where(ItemTag.tag == tag.strip().lower())))
    if author:
        stmt = stmt.where(Item.owner_id.in_(select(User.id).where(User.handle == author.strip().lower())))
    if official is not None:
        stmt = stmt.where(Item.official.is_(official))
    if asset_kind:
        if asset_kind not in ASSET_KINDS:
            raise ApiError(422, "invalid_request", fields="asset_kind")
        stmt = stmt.where(Item.asset_kind == asset_kind)
    column = {"trending": Item.trend_score, "new": Item.created_at, "downloads": Item.downloads_total}[sort]
    attribute = {"trending": "trend_score", "new": "created_at", "downloads": "downloads_total"}[sort]
    rows, next_cursor = paginate(
        db, stmt, keys=[column, Item.id], cursor=cursor, limit=limit,
        key_of=lambda row: [getattr(row, attribute), row.id],
    )
    return {"items": item_summaries(ctx, db, rows), "next_cursor": next_cursor}


def item_detail(ctx: Context, db: Session, item: Item, principal: Principal | None) -> dict:
    owner = db.get(User, item.owner_id)
    assert owner is not None
    detail = item_summary(ctx, db, item, owner, tags_by_item(db, [item.id]).get(item.id, []))
    current = db.get(ItemVersion, item.current_version_id) if item.current_version_id else None
    latest = db.scalars(
        select(ItemVersion).where(ItemVersion.item_id == item.id).order_by(ItemVersion.number.desc()).limit(1)
    ).first()
    is_owner = principal is not None and (principal.user.id == item.owner_id or principal.is_moderator)
    detail.update(
        {
            "description": item.description,
            "extra": item.extra or {},
            "current_version": version_out(current) if current else None,
            "versions_count": db.scalar(
                select(func.count()).select_from(ItemVersion).where(
                    ItemVersion.item_id == item.id, ItemVersion.status == VERSION_APPROVED
                )
            ),
            "download_url": download_path(item) if current else None,
            "downloads_30d": item_series(db, item.id, "downloads", 30),
            "liked": (
                db.get(Like, (principal.user.id, item.id)) is not None if principal is not None else None
            ),
        }
    )
    if is_owner and latest is not None:
        detail["latest_submission"] = version_out(latest, include_review=True)
    meta = (current.meta if current else None) or {}
    if item.kind == KIND_ASSET:
        # 还没有公开版本时(真人人物在审核),作者和审核员看的是最近一次提交。
        shown = current if current is not None else (latest if is_owner else None)
        bundle = ((shown.meta if shown else None) or {}).get("bundle") or {}
        detail["bundle"] = bundle or None
        detail["media"] = asset_media(ctx, db, bundle) if bundle else {}
        if is_owner and shown is not None:
            detail["consent_kind"] = (shown.meta or {}).get("consent_kind") or None
        return detail
    if item.kind == KIND_WORKFLOW:
        graphs = meta.get("graphs") or {}
        detail["graph"] = graphs.get(current_locale()) or meta.get("graph")
        detail["code_node_types"] = (meta.get("summary") or {}).get("code_node_types", [])
        detail["plugin_ids"] = (meta.get("summary") or {}).get("plugin_ids", [])
    else:
        entry = dict(meta.get("index_entry") or {})
        if entry:
            entry["download"] = public_download_url(ctx, item, current)
        detail["index_entry"] = ordered_entry(entry) if entry else None
        detail["files_count"] = len(meta.get("files") or [])
    return detail


def ordered_entry(entry: dict) -> dict:
    """按发版产物 registry.json 的键序排(Postgres 的 JSONB 不保留键序)。"""
    return {key: entry.get(key) for key in ENTRY_KEYS}


def public_download_url(ctx: Context, item: Item, version: ItemVersion | None) -> str:
    if version is not None and version.external_download:
        return version.external_download
    return f"{ctx.settings.public_url}{download_path(item, version)}"


def build_router(kind: str) -> APIRouter:
    path = f"/{KIND_PATHS[kind]}"
    router = APIRouter(prefix=path, tags=[KIND_PATHS[kind]])

    if kind == KIND_PLUGIN:

        @router.get("/index.json")
        def plugin_index(
            ctx: Ctx, db: Db, include: str | None = Query(default=None, description="`official` 连官方条目一起给")
        ) -> JSONResponse:
            """给应用读的插件索引,字段与发版产物 `registry.json` 相同。缺省只有社区提交的插件。"""
            stmt = public_items(KIND_PLUGIN)
            if include != "official":
                stmt = stmt.where(Item.official.is_(False))
            items = list(db.scalars(stmt.order_by(Item.slug)))
            current = {
                version.id: version
                for version in db.scalars(select(ItemVersion).where(ItemVersion.id.in_({one.current_version_id for one in items})))
            }
            plugins = []
            for item in items:
                version = current.get(item.current_version_id or "")
                entry = dict((version.meta or {}).get("index_entry") or {}) if version else {}
                if not entry or entry.get("bundled"):
                    continue
                entry["download"] = public_download_url(ctx, item, version)
                plugins.append(ordered_entry(entry))
            return JSONResponse({"channel": "community", "plugins": plugins}, headers={"Cache-Control": "public, max-age=60"})

    @router.get("")
    def list_(
        ctx: Ctx,
        db: Db,
        q: str | None = Query(default=None, max_length=100),
        tag: str | None = Query(default=None, max_length=32),
        sort: str = "trending",
        author: str | None = Query(default=None, max_length=32),
        official: bool | None = None,
        cursor: str | None = None,
        limit: int | None = Query(default=None, ge=1, le=50),
        asset_kind: str | None = Query(default=None, max_length=16, description="只对 /assets:character / location / prop"),
    ) -> dict:
        return list_items(
            ctx, db, kind, q=q, tag=tag, sort=sort, author=author, official=official, cursor=cursor, limit=limit,
            asset_kind=asset_kind if kind == KIND_ASSET else None,
        )

    if kind != KIND_ASSET:

        @router.post("", status_code=201)
        async def create(
            principal: CurrentUser,
            ctx: Ctx,
            db: Db,
            file: Annotated[UploadFile | None, File()] = None,
            title: Annotated[str | None, Form(max_length=200)] = None,
            summary: Annotated[str | None, Form(max_length=1000)] = None,
            description: Annotated[str | None, Form(max_length=40000)] = None,
            tags: Annotated[str | None, Form(max_length=1000)] = None,
            changelog: Annotated[str, Form(max_length=10000)] = "",
            cover: Annotated[UploadFile | None, File()] = None,
        ) -> JSONResponse:
            limit = ctx.settings.workflow_max_bytes if kind == KIND_WORKFLOW else ctx.settings.plugin_max_bytes
            data = await read_upload(file, limit)
            cover_data = await read_optional(cover, ctx.settings.cover_max_bytes)
            meta = Metadata(title=title, summary=summary, description=description, tags=parse_tags(tags), changelog=changelog)
            if kind == KIND_WORKFLOW:
                item, version = submit_workflow(ctx, db, principal.user, data, meta, cover=cover_data)
            else:
                item, version = submit_plugin(ctx, db, principal.user, data, meta, cover=cover_data)
            db.commit()
            return JSONResponse(
                {**item_detail(ctx, db, item, principal), "submission": version_out(version, include_review=True)}, status_code=201
            )

    else:

        @router.post("", status_code=201)
        def create_asset(body: AssetIn, principal: CurrentUser, ctx: Ctx, db: Db) -> JSONResponse:
            """提交一个资产:分享包里的参考图要已经走完三步上传(`/shares/uploads` → PUT)。"""
            item, version = submit_asset(ctx, db, principal.user, body.bundle, body.consent_kind, body.metadata())
            db.commit()
            return JSONResponse(
                {**item_detail(ctx, db, item, principal), "submission": version_out(version, include_review=True)},
                status_code=201,
            )

    @router.get("/{slug}")
    def detail(slug: str, principal: MaybeUser, ctx: Ctx, db: Db) -> dict:
        item = get_item(db, kind, slug, principal)
        if item.current_version_id is not None and (principal is None or principal.user.id != item.owner_id):
            bump(db, item, "views")
            db.commit()
        return item_detail(ctx, db, item, principal)

    @router.get("/{slug}/versions")
    def versions_(
        slug: str,
        principal: MaybeUser,
        db: Db,
        cursor: str | None = None,
        limit: int | None = Query(default=None, ge=1, le=50),
    ) -> dict:
        item = get_item(db, kind, slug, principal)
        is_owner = principal is not None and (principal.user.id == item.owner_id or principal.is_moderator)
        stmt = select(ItemVersion).where(ItemVersion.item_id == item.id)
        if not is_owner:
            stmt = stmt.where(ItemVersion.status == VERSION_APPROVED)
        rows, next_cursor = paginate(
            db, stmt, keys=[ItemVersion.number, ItemVersion.id], cursor=cursor, limit=limit,
            key_of=lambda row: [row.number, row.id],
        )
        return {"items": [version_out(row, include_review=is_owner) for row in rows], "next_cursor": next_cursor}

    if kind != KIND_ASSET:

        @router.post("/{slug}/versions", status_code=201)
        async def new_version(
            slug: str,
            principal: CurrentUser,
            ctx: Ctx,
            db: Db,
            file: Annotated[UploadFile | None, File()] = None,
            changelog: Annotated[str, Form(max_length=10000)] = "",
            title: Annotated[str | None, Form(max_length=200)] = None,
            summary: Annotated[str | None, Form(max_length=1000)] = None,
            description: Annotated[str | None, Form(max_length=40000)] = None,
            tags: Annotated[str | None, Form(max_length=1000)] = None,
            cover: Annotated[UploadFile | None, File()] = None,
        ) -> JSONResponse:
            """发新版本。标题、简介、标签、封面可以一起改(给了才改)。"""
            item = get_item(db, kind, slug, principal)
            if item.owner_id != principal.user.id:
                raise ApiError(403, "not_owner")
            limit = ctx.settings.workflow_max_bytes if kind == KIND_WORKFLOW else ctx.settings.plugin_max_bytes
            data = await read_upload(file, limit)
            cover_data = await read_optional(cover, ctx.settings.cover_max_bytes)
            meta = Metadata(title=title, summary=summary, description=description, tags=parse_tags(tags), changelog=changelog)
            if kind == KIND_WORKFLOW:
                item, version = submit_workflow(ctx, db, principal.user, data, meta, cover=cover_data, item=item)
            else:
                item, version = submit_plugin(ctx, db, principal.user, data, meta, cover=cover_data, expect_item=item)
            db.commit()
            return JSONResponse(version_out(version, include_review=True), status_code=201)

    else:

        @router.post("/{slug}/versions", status_code=201)
        def new_asset_version(slug: str, body: AssetIn, principal: CurrentUser, ctx: Ctx, db: Db) -> JSONResponse:
            """资产的新版本。标题、简介、标签一起改(给了才改);种类不能换。"""
            item = get_item(db, kind, slug, principal)
            if item.owner_id != principal.user.id:
                raise ApiError(403, "not_owner")
            item, version = submit_asset(ctx, db, principal.user, body.bundle, body.consent_kind, body.metadata(), item=item)
            db.commit()
            return JSONResponse(version_out(version, include_review=True), status_code=201)

    @router.get("/{slug}/download")
    def download(
        slug: str,
        principal: MaybeUser,
        ctx: Ctx,
        db: Db,
        version: str | None = Query(default=None, max_length=64),
        locale: str | None = Query(default=None, max_length=8),
    ) -> Response:
        """计一次下载,然后 302 到文件(下载型文件一律 attachment);资产直接回分享包。"""
        item = get_item(db, kind, slug, principal)
        is_owner = principal is not None and (principal.user.id == item.owner_id or principal.is_moderator)
        if version:
            target = db.scalars(select(ItemVersion).where(ItemVersion.item_id == item.id, ItemVersion.version == version)).first()
            if target is None or (target.status != VERSION_APPROVED and not is_owner):
                raise ApiError(404, "item_not_found")
        else:
            target = db.get(ItemVersion, item.current_version_id) if item.current_version_id else None
            if target is None:
                raise ApiError(404, "item_not_found")
        if target.status == VERSION_APPROVED:
            bump(db, item, "downloads")
            db.commit()
        if kind == KIND_ASSET:
            # 资产没有「一个文件」:直接回分享包和每张参考图的地址,应用拿它导入(ADR 0027 §4)。
            bundle = (target.meta or {}).get("bundle") or {}
            return JSONResponse(
                {"slug": item.slug, "version": target.version, "bundle": bundle, "media": asset_media(ctx, db, bundle, absolute=True)},
                headers={"Cache-Control": "no-store"},
            )
        if target.external_download:
            return RedirectResponse(target.external_download, status_code=302)
        key, name = target.file_key, None
        localized = target.localized_files or {}
        want = locale or current_locale()
        if want in localized:
            key = localized[want]["key"]
        if not key:
            raise ApiError(404, "item_not_found")
        name = key.rsplit("/", 1)[-1]
        return RedirectResponse(ctx.storage.download_url(key, name), status_code=302)

    @router.post("/{slug}/like")
    def like(slug: str, principal: CurrentUser, db: Db) -> dict:
        item = get_item(db, kind, slug, principal)
        if db.get(Like, (principal.user.id, item.id)) is None:
            db.add(Like(user_id=principal.user.id, item_id=item.id))
            bump(db, item, "likes", 1)
            db.commit()
        return {"liked": True, "likes": item.likes_total}

    @router.delete("/{slug}/like")
    def unlike(slug: str, principal: CurrentUser, db: Db) -> dict:
        item = get_item(db, kind, slug, principal)
        existing = db.get(Like, (principal.user.id, item.id))
        if existing is not None:
            db.delete(existing)
            bump(db, item, "likes", -1)
            db.commit()
        return {"liked": False, "likes": item.likes_total}

    @router.post("/{slug}/report", status_code=201)
    def report(slug: str, body: ReportIn, principal: CurrentUser, db: Db) -> dict:
        """举报 → 进审核队列(`GET /admin/reports`)。"""
        item = get_item(db, kind, slug, principal)
        return {"id": file_report(db, principal, kind, item.id, body).id}

    return router


def file_report(db: Session, principal: Principal, target_kind: str, target_id: str, body: ReportIn) -> Report:
    if body.reason not in REPORT_REASONS:
        raise ApiError(422, "report_reason_invalid")
    duplicate = db.scalar(
        select(func.count()).select_from(Report).where(
            Report.target_kind == target_kind,
            Report.target_id == target_id,
            Report.reporter_id == principal.user.id,
            Report.status == REPORT_OPEN,
        )
    )
    if duplicate:
        raise ApiError(409, "report_duplicate")
    row = Report(target_kind=target_kind, target_id=target_id, reporter_id=principal.user.id, reason=body.reason, detail=body.detail)
    db.add(row)
    db.commit()
    return row


workflows_router = build_router(KIND_WORKFLOW)
plugins_router = build_router(KIND_PLUGIN)
assets_router = build_router(KIND_ASSET)

__all__ = ["REPORT_REASONS", "ReportIn", "file_report", "get_item", "plugins_router", "workflows_router"]
