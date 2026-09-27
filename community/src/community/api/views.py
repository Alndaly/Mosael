"""把表里的行变成接口回的 JSON。各路由共用这一份,同一个东西在哪儿都长一个样。"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from community.config import API_PREFIX
from community.context import Context
from community.models import (
    KIND_ASSET,
    KIND_PLUGIN,
    KIND_WORKFLOW,
    ROLE_USER,
    Blob,
    Item,
    ItemTag,
    ItemVersion,
    Share,
    ShareVersion,
    User,
)
from community.security import mask_phone

KIND_PATHS = {KIND_WORKFLOW: "workflows", KIND_PLUGIN: "plugins", KIND_ASSET: "assets"}


def iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def blob_url(ctx: Context, db: Session, sha256: str | None) -> str | None:
    if not sha256:
        return None
    blob = db.get(Blob, sha256)
    return ctx.storage.media_url(blob.storage_key) if blob is not None else None


def public_user(ctx: Context, db: Session, user: User) -> dict:
    return {
        "handle": user.handle,
        "display_name": user.display_name or user.handle,
        "avatar_url": blob_url(ctx, db, user.avatar_sha256),
        "official": user.is_official,
        "created_at": iso(user.created_at),
    }


def me_user(ctx: Context, db: Session, user: User) -> dict:
    return {
        "id": user.id,
        **public_user(ctx, db, user),
        "role": user.role or ROLE_USER,
        "status": user.status,
        "phone": mask_phone(user.phone),
        "has_password": bool(user.password_hash),
        "handle_changeable": user.handle_changed_at is None,
        "terms_version": user.terms_version,
    }


def users_by_id(db: Session, ids: Iterable[str]) -> dict[str, User]:
    wanted = set(ids)
    if not wanted:
        return {}
    return {user.id: user for user in db.scalars(select(User).where(User.id.in_(wanted)))}


def tags_by_item(db: Session, ids: Iterable[str]) -> dict[str, list[str]]:
    wanted = set(ids)
    out: dict[str, list[str]] = {one: [] for one in wanted}
    if wanted:
        for item_id, tag in db.execute(select(ItemTag.item_id, ItemTag.tag).where(ItemTag.item_id.in_(wanted))):
            out[item_id].append(tag)
    return {key: sorted(value) for key, value in out.items()}


def item_summary(ctx: Context, db: Session, item: Item, owner: User, tags: list[str]) -> dict:
    base = {
        "kind": item.kind,
        "slug": item.slug,
        "title": item.title,
        "summary": item.summary,
        "tags": tags,
        "cover_url": blob_url(ctx, db, item.cover_sha256),
        "official": item.official,
        "author": public_user(ctx, db, owner),
        "version": item.version_label or None,
        "published": item.current_version_id is not None,
        "hidden": item.hidden_at is not None,
        "downloads": item.downloads_total,
        "likes": item.likes_total,
        "views": item.views_total,
        "created_at": iso(item.created_at),
        "updated_at": iso(item.updated_at),
    }
    if item.kind == KIND_WORKFLOW:
        base.update({"has_code": item.has_code, "node_count": item.node_count})
    elif item.kind == KIND_ASSET:
        extra = item.extra or {}
        base.update(
            {
                "asset_kind": item.asset_kind,
                "real_person": bool(extra.get("real_person")),
                "reference_count": int(extra.get("reference_count") or 0),
                "variant_count": int(extra.get("variant_count") or 0),
            }
        )
    else:
        extra = item.extra or {}
        base.update(
            {
                "plugin_id": item.plugin_id,
                "permissions": extra.get("permissions", []),
                "runtime": extra.get("runtime", "process"),
            }
        )
    return base


def item_summaries(ctx: Context, db: Session, items: list[Item]) -> list[dict]:
    owners = users_by_id(db, (item.owner_id for item in items))
    tags = tags_by_item(db, (item.id for item in items))
    return [item_summary(ctx, db, item, owners[item.owner_id], tags.get(item.id, [])) for item in items]


def download_path(item: Item, version: ItemVersion | None = None) -> str:
    path = f"{API_PREFIX}/{KIND_PATHS[item.kind]}/{item.slug}/download"
    return f"{path}?version={version.version}" if version is not None else path


def version_out(version: ItemVersion, *, include_review: bool = False) -> dict:
    out = {
        "id": version.id,
        "number": version.number,
        "version": version.version,
        "created_at": iso(version.created_at),
        "changelog": version.changelog,
        "size": version.file_size,
        "sha256": version.file_sha256 or None,
    }
    if include_review:
        out.update({"status": version.status, "review_note": version.review_note, "reviewed_at": iso(version.reviewed_at)})
    return out


def share_media(ctx: Context, db: Session, hashes: Iterable[str]) -> dict[str, dict]:
    wanted = set(hashes)
    if not wanted:
        return {}
    return {
        blob.sha256: {"url": ctx.storage.media_url(blob.storage_key), "content_type": blob.content_type, "size": blob.size}
        for blob in db.scalars(select(Blob).where(Blob.sha256.in_(wanted)))
    }


def share_url(ctx: Context, share: Share, locale: str) -> str:
    return f"{ctx.settings.public_url}/{locale}/b/{share.slug}"


def og_path(share: Share) -> str:
    return f"{API_PREFIX}/shares/{share.slug}/og.png"


def share_summary(ctx: Context, db: Session, share: Share, owner: User, version: ShareVersion | None, locale: str) -> dict:
    cover = None
    if version is not None:
        for item in (version.snapshot or {}).get("items", []):
            media = item.get("media") if isinstance(item, dict) else None
            if isinstance(media, dict) and str(media.get("content_type", "")).startswith("image/"):
                cover = blob_url(ctx, db, media.get("thumb_sha256") or media.get("sha256"))
                if cover:
                    break
    return {
        "slug": share.slug,
        "title": share.title,
        "visibility": share.visibility,
        "version": version.number if version else None,
        "item_count": version.item_count if version else 0,
        "url": share_url(ctx, share, locale),
        "cover_url": cover,
        "og_image_url": og_path(share),
        "owner": public_user(ctx, db, owner),
        "created_at": iso(share.created_at),
        "updated_at": iso(share.updated_at),
    }


__all__ = [
    "KIND_PATHS",
    "blob_url",
    "download_path",
    "iso",
    "item_summaries",
    "item_summary",
    "me_user",
    "og_path",
    "public_user",
    "share_media",
    "share_summary",
    "share_url",
    "tags_by_item",
    "users_by_id",
    "version_out",
]
