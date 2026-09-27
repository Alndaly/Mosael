"""提交工作流、插件与资产:收文件、过同一套格式校验、落存储、建版本(ADR 0026 第 4 节、ADR 0027 §4)。

- **工作流**发布即上架:它是数据,不在别人机器上执行代码;含「运行代码」节点的在详情里醒目标出。
- **插件**先进审核队列(`pending`),`moderator` 以上通过后才公开 —— 插件会在别人的电脑上运行代码。
- **资产**(人物 / 场景 / 道具)是一个分享包 `mosael.asset/1`,参考图先走三步上传、按哈希引用。虚构的
  发布即上架;**真人**人物须声明「本人」或「已取得本人同意公开」,并先进审核队列(肖像是这个人的)。
- 同一作者再提交同一项 = 新版本;插件的 id 由第一个提交者占有。

路由(api/items.py)只管 HTTP;这里的函数不认识 Request,测试和官方条目导入(catalog.py)直接调它们。
"""

from __future__ import annotations

import json
import logging
import re
import secrets
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from community.context import Context
from community.crypto import sha256_hex
from community.db import utcnow
from community.errors import ApiError, human_size
from community.logs import log_event
from community.blobs import claim_ready
from community.models import (
    KIND_ASSET,
    KIND_PLUGIN,
    KIND_WORKFLOW,
    VERSION_APPROVED,
    VERSION_PENDING,
    VERSION_REJECTED,
    Blob,
    BlobOwner,
    Item,
    ItemTag,
    ItemVersion,
    User,
)
from community.storage import IMAGE_TYPES, attachment, blob_key
from mosael_formats import asset_bundle, plugin_archive, versions, workflow_file
from mosael_formats.i18n import FormatError, pick_text
from mosael_formats.plugin_index import index_entry

logger = logging.getLogger(__name__)

MAX_TITLE_CHARS = 120
MAX_SUMMARY_CHARS = 300
MAX_DESCRIPTION_CHARS = 20_000
MAX_CHANGELOG_CHARS = 5_000
MAX_TAGS = 8
MAX_TAG_CHARS = 32
SLUG_SAFE = re.compile(r"[^a-z0-9]+")
#: slug 不能和这些路由撞(`/plugins/index.json`,官网的 `/workflows/new`、`/plugins/new` 等静态页)。
RESERVED_SLUGS = frozenset({"index.json", "new", "new-version"})

_IMAGE_MAGIC = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
)


@dataclass
class Metadata:
    title: str | None = None
    summary: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    changelog: str = ""


def sniff_image(data: bytes) -> str | None:
    """认一张图片的真实类型(只认 png / jpeg / gif / webp / avif)。认不出返回 None。"""
    for magic, content_type in _IMAGE_MAGIC:
        if data.startswith(magic):
            return content_type
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[4:12] in (b"ftypavif", b"ftypavis"):
        return "image/avif"
    return None


def parse_tags(raw: str | list[str] | None) -> list[str] | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if text.startswith("["):
            try:
                values = json.loads(text)
            except ValueError as exc:
                raise ApiError(422, "tags_invalid") from exc
        else:
            values = [one for one in re.split(r"[,，]", text)]
    else:
        values = raw
    tags: list[str] = []
    for value in values:
        tag = str(value).strip().lower()
        if not tag:
            continue
        if len(tag) > MAX_TAG_CHARS or "," in tag:
            raise ApiError(422, "tags_invalid")
        if tag not in tags:
            tags.append(tag)
    if len(tags) > MAX_TAGS:
        raise ApiError(422, "tags_invalid")
    return tags


def _check_title(title: str) -> str:
    title = title.strip()
    if not title:
        raise ApiError(422, "title_required")
    if len(title) > MAX_TITLE_CHARS:
        raise ApiError(422, "title_too_long")
    return title


def search_text(*parts: Any) -> str:
    chunks: list[str] = []
    for part in parts:
        if isinstance(part, dict):
            chunks.extend(str(value) for value in part.values() if isinstance(value, str))
        elif isinstance(part, list):
            chunks.extend(str(value) for value in part)
        elif part:
            chunks.append(str(part))
    return " ".join(chunks).lower()[:20_000]


def set_tags(db: Session, item: Item, tags: list[str]) -> None:
    for existing in db.scalars(select(ItemTag).where(ItemTag.item_id == item.id)):
        db.delete(existing)
    db.flush()
    for tag in tags:
        db.add(ItemTag(item_id=item.id, tag=tag))


def unique_slug(db: Session, kind: str, base: str) -> str:
    base = SLUG_SAFE.sub("-", base.lower()).strip("-")[:60]
    if len(base) < 3:
        base = f"{ {KIND_WORKFLOW: 'wf', KIND_ASSET: 'a'}.get(kind, 'p') }-{secrets.token_hex(4)}"
    if base in RESERVED_SLUGS:
        base = f"{base}-{secrets.token_hex(2)}"
    candidate = base
    for counter in range(2, 50):
        if db.scalar(select(func.count()).select_from(Item).where(Item.kind == kind, Item.slug == candidate)) == 0:
            return candidate
        candidate = f"{base}-{counter}"
    return f"{base}-{secrets.token_hex(3)}"


def store_blob(ctx: Context, db: Session, user: User, data: bytes, content_type: str) -> Blob:
    """一份内容寻址的文件(封面、官方条目的图),同一份内容只存一次。"""
    sha = sha256_hex(data)
    blob = db.get(Blob, sha)
    if blob is None:
        blob = Blob(sha256=sha, size=len(data), content_type=content_type, storage_key=blob_key(sha, content_type))
        db.add(blob)
    if blob.status != "ready":
        ctx.storage.put_bytes(blob.storage_key, data, content_type=content_type)
        blob.status, blob.verified_at, blob.size = "ready", utcnow(), len(data)
    if db.get(BlobOwner, (user.id, sha)) is None:
        db.add(BlobOwner(user_id=user.id, sha256=sha))
    db.flush()
    return blob


def store_cover(ctx: Context, db: Session, user: User, data: bytes | None) -> str | None:
    if not data:
        return None
    if len(data) > ctx.settings.cover_max_bytes:
        raise ApiError(413, "file_too_large", limit=human_size(ctx.settings.cover_max_bytes))
    content_type = sniff_image(data)
    if content_type not in IMAGE_TYPES or content_type == "image/gif":
        raise ApiError(422, "cover_invalid")
    return store_blob(ctx, db, user, data, content_type).sha256


def _next_number(db: Session, item: Item) -> int:
    return int(db.scalar(select(func.coalesce(func.max(ItemVersion.number), 0)).where(ItemVersion.item_id == item.id)) or 0) + 1


def _file_key(kind: str, item: Item, version: ItemVersion, filename: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", filename)[:120]
    return f"files/{kind}s/{item.id}/{version.id}/{safe}"


# ---------------- 工作流 ----------------


def read_workflow(data: bytes) -> tuple[workflow_file.WorkflowFile, workflow_file.GraphSummary]:
    try:
        document = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ApiError.from_format(workflow_file.WorkflowFileError("workflowFileErr_notWorkflowFile")) from exc
    try:
        envelope = workflow_file.read_workflow_file(document)
        workflow_file.check_graph(envelope.graph)
    except FormatError as exc:
        raise ApiError.from_format(exc) from exc
    return envelope, workflow_file.summarize_graph(envelope.graph)


def _workflow_meta(envelope: workflow_file.WorkflowFile, summary: workflow_file.GraphSummary) -> dict:
    return {
        "graph": envelope.graph,
        "file_name": envelope.name,
        "summary": {
            "node_count": summary.node_count,
            "node_types": summary.node_types,
            "code_node_types": summary.code_node_types,
            "plugin_ids": summary.plugin_ids,
        },
    }


def submit_workflow(
    ctx: Context, db: Session, user: User, data: bytes, meta: Metadata, *, cover: bytes | None = None, item: Item | None = None
) -> tuple[Item, ItemVersion]:
    """新建一个工作流(item 为空)或给它发一个新版本。发布即上架。"""
    if len(data) > ctx.settings.workflow_max_bytes:
        raise ApiError(413, "file_too_large", limit=human_size(ctx.settings.workflow_max_bytes))
    envelope, summary = read_workflow(data)
    now = utcnow()
    if item is None:
        title = _check_title(meta.title or envelope.name)
        item = Item(
            kind=KIND_WORKFLOW,
            slug=unique_slug(db, KIND_WORKFLOW, title),
            owner_id=user.id,
            title=title,
            summary=(meta.summary if meta.summary is not None else envelope.description)[:MAX_SUMMARY_CHARS],
            description=(meta.description if meta.description is not None else envelope.description)[:MAX_DESCRIPTION_CHARS],
            extra={},
            created_at=now,
        )
        db.add(item)
        db.flush()
        set_tags(db, item, meta.tags or [])
        cover_sha = store_cover(ctx, db, user, cover)
        if cover_sha:
            item.cover_sha256 = cover_sha
        item.search_text = search_text(item.title, item.summary, meta.tags or [], item.slug)
    elif item.owner_id != user.id:
        raise ApiError(403, "not_owner")
    else:
        update_metadata(ctx, db, item, user, meta, cover)
    number = _next_number(db, item)
    version = ItemVersion(
        item_id=item.id,
        number=number,
        version=str(number),
        status=VERSION_APPROVED,
        submitter_id=user.id,
        file_sha256=sha256_hex(data),
        file_size=len(data),
        meta=_workflow_meta(envelope, summary),
        changelog=meta.changelog[:MAX_CHANGELOG_CHARS],
        reviewed_at=now,
        created_at=now,
    )
    db.add(version)
    db.flush()
    version.file_key = _file_key(KIND_WORKFLOW, item, version, f"{item.slug}{workflow_file.SUFFIX}")
    ctx.storage.put_bytes(
        version.file_key, data, content_type="application/json",
        disposition=attachment(f"{item.slug}{workflow_file.SUFFIX}"),
    )
    publish_version(item, version)
    db.flush()
    log_event(logger, "workflow submitted", item_id=item.id, version=version.number, user_id=user.id)
    return item, version


def update_metadata(ctx: Context, db: Session, item: Item, user: User, meta: Metadata, cover: bytes | None) -> None:
    """发新版本时顺带改的标题、简介、标签、封面(给了才改)。"""
    if meta.title is not None and meta.title.strip():
        item.title = _check_title(meta.title)
    if meta.summary is not None:
        item.summary = meta.summary[:MAX_SUMMARY_CHARS]
    if meta.description is not None:
        item.description = meta.description[:MAX_DESCRIPTION_CHARS]
    if meta.tags is not None:
        set_tags(db, item, meta.tags)
    cover_sha = store_cover(ctx, db, user, cover)
    if cover_sha:
        item.cover_sha256 = cover_sha
    tags = meta.tags if meta.tags is not None else [row.tag for row in db.scalars(select(ItemTag).where(ItemTag.item_id == item.id))]
    item.search_text = search_text(item.title, item.summary, tags, item.slug)


def publish_version(item: Item, version: ItemVersion) -> None:
    """让这一版成为当前公开的那一版,列表用的几样摘要跟着换。"""
    item.current_version_id = version.id
    item.version_label = version.version
    item.updated_at = utcnow()
    if item.kind == KIND_WORKFLOW:
        summary = (version.meta or {}).get("summary") or {}
        item.has_code = bool(summary.get("code_node_types"))
        item.node_count = int(summary.get("node_count") or 0)
    elif item.kind == KIND_ASSET:
        bundle = (version.meta or {}).get("bundle") or {}
        item.asset_kind = bundle.get("kind")
        item.cover_sha256 = bundle.get("cover_sha256") or item.cover_sha256
        references = len(bundle.get("references") or []) + sum(len(one.get("references") or []) for one in bundle.get("variants") or [])
        item.extra = {
            **(item.extra or {}),
            "real_person": bool((bundle.get("attributes") or {}).get("real_person")),
            "reference_count": references,
            "variant_count": len(bundle.get("variants") or []),
        }
    else:
        entry = (version.meta or {}).get("index_entry") or {}
        item.extra = {**(item.extra or {}), "permissions": entry.get("permissions", []), "runtime": entry.get("runtime", "process")}


# ---------------- 插件 ----------------


def read_plugin(ctx: Context, data: bytes) -> plugin_archive.PluginArchive:
    settings = ctx.settings
    if len(data) > settings.plugin_max_bytes:
        raise ApiError(413, "file_too_large", limit=human_size(settings.plugin_max_bytes))
    try:
        return plugin_archive.read_plugin_archive(
            data,
            max_archive_bytes=settings.plugin_max_bytes,
            max_unpacked_bytes=settings.plugin_max_unpacked_bytes,
            max_files=settings.plugin_max_files,
        )
    except FormatError as exc:
        raise ApiError.from_format(exc) from exc


def _latest_live(db: Session, item: Item) -> ItemVersion | None:
    """最近一次没被拒的提交。新版本必须比它新。"""
    return db.scalars(
        select(ItemVersion)
        .where(ItemVersion.item_id == item.id, ItemVersion.status != VERSION_REJECTED)
        .order_by(ItemVersion.number.desc())
        .limit(1)
    ).first()


def submit_plugin(
    ctx: Context,
    db: Session,
    user: User,
    data: bytes,
    meta: Metadata,
    *,
    cover: bytes | None = None,
    expect_item: Item | None = None,
) -> tuple[Item, ItemVersion]:
    """收一个插件包。清单 id 第一次出现 = 新插件(提交者占有这个 id);已有且是自己的 = 新版本。进审核队列。"""
    package = read_plugin(ctx, data)
    manifest = package.manifest
    if not versions.is_semver(manifest.version):
        raise ApiError(422, "plugin_version_invalid", version=manifest.version)
    if manifest.id.lower() in RESERVED_SLUGS:
        raise ApiError(409, "plugin_id_taken", plugin_id=manifest.id)
    item = db.scalars(select(Item).where(Item.plugin_id == manifest.id)).first()
    if expect_item is not None and (item is None or item.id != expect_item.id):
        raise ApiError(422, "plugin_id_mismatch", plugin_id=manifest.id)
    if item is not None and item.owner_id != user.id:
        raise ApiError(409, "plugin_id_taken", plugin_id=manifest.id)
    entry = index_entry(package.raw, download="", bundled=False)
    now = utcnow()
    if item is None and db.scalar(
        select(func.count()).select_from(Item).where(Item.kind == KIND_PLUGIN, Item.slug == manifest.id)
    ):
        # 插件的 slug 就是它的 id;官方条目的 slug 是目录名(如 baidu-pan),也不能被一个同名 id 顶掉。
        raise ApiError(409, "plugin_id_taken", plugin_id=manifest.id)
    if item is None:
        title = meta.title.strip() if meta.title and meta.title.strip() else package.raw.get("name")
        if isinstance(title, str):
            title = _check_title(title)
        elif not pick_text(title).strip():
            raise ApiError(422, "title_required")
        summary = meta.summary if meta.summary is not None else entry["description"]
        item = Item(
            kind=KIND_PLUGIN,
            slug=manifest.id,
            plugin_id=manifest.id,
            owner_id=user.id,
            title=title,
            summary=summary[:MAX_SUMMARY_CHARS] if isinstance(summary, str) else summary,
            description=(meta.description or "")[:MAX_DESCRIPTION_CHARS],
            extra={"permissions": entry["permissions"], "runtime": entry["runtime"]},
            created_at=now,
        )
        db.add(item)
        db.flush()
        set_tags(db, item, meta.tags or [])
        item.search_text = search_text(item.title, item.summary, meta.tags or [], manifest.id)
    else:
        if db.scalar(
            select(func.count()).select_from(ItemVersion).where(ItemVersion.item_id == item.id, ItemVersion.version == manifest.version)
        ):
            raise ApiError(409, "version_exists", version=manifest.version)
        latest = _latest_live(db, item)
        if latest is not None and versions.compare(manifest.version, latest.version) != 1:
            raise ApiError(409, "version_not_newer", version=manifest.version, latest=latest.version)
        update_metadata(ctx, db, item, user, meta, cover)
        cover = None
    cover_sha = store_cover(ctx, db, user, cover)
    if cover_sha:
        item.cover_sha256 = cover_sha
    version = ItemVersion(
        item_id=item.id,
        number=_next_number(db, item),
        version=manifest.version,
        status=VERSION_PENDING,
        submitter_id=user.id,
        file_sha256=sha256_hex(data),
        file_size=len(data),
        meta={
            "manifest": package.raw,
            "files": [{"path": one.path, "size": one.size, "sha256": one.sha256} for one in package.files],
            "index_entry": entry,
        },
        changelog=meta.changelog[:MAX_CHANGELOG_CHARS],
        created_at=now,
    )
    db.add(version)
    db.flush()
    filename = f"{manifest.id}-{manifest.version}.zip"
    version.file_key = _file_key(KIND_PLUGIN, item, version, filename)
    ctx.storage.put_bytes(version.file_key, data, content_type="application/zip", disposition=attachment(filename))
    db.flush()
    log_event(logger, "plugin submitted", item_id=item.id, version=manifest.version, user_id=user.id)
    return item, version


# ---------------- 资产 ----------------


def read_asset(bundle: Any, consent_kind: Any) -> tuple[asset_bundle.AssetBundleSummary, str]:
    """过 mosael_formats.asset_bundle 的校验(桌面端导出、别人导入过的是同一份),回摘要与规整后的授权声明。"""
    try:
        summary = asset_bundle.validate_bundle(bundle)
        consent = asset_bundle.check_consent(summary, consent_kind)
    except FormatError as exc:
        raise ApiError.from_format(exc, code="invalid_asset_bundle") from exc
    return summary, consent


def submit_asset(
    ctx: Context,
    db: Session,
    user: User,
    bundle: Any,
    consent_kind: Any,
    meta: Metadata,
    *,
    item: Item | None = None,
) -> tuple[Item, ItemVersion]:
    """新建一个资产(item 为空)或给它发一个新版本。

    参考图只以哈希出现在包里,必须都是提交者自己上传过、核对过的文件(blobs.claim_ready)—— 和画板快照一样。
    虚构的发布即上架;真人人物进审核队列,审核界面并排看参考图和授权声明。种类定下就不能改:
    同一个资产的新版本从人物变成道具,别人导入的那一份就对不上了。
    """
    summary, consent = read_asset(bundle, consent_kind)
    claim_ready(ctx, db, user, summary.hashes)
    now = utcnow()
    if item is None:
        title = _check_title(meta.title or summary.name)
        item = Item(
            kind=KIND_ASSET,
            slug=unique_slug(db, KIND_ASSET, title),
            owner_id=user.id,
            title=title,
            summary=(meta.summary if meta.summary is not None else (bundle.get("description") or ""))[:MAX_SUMMARY_CHARS],
            description=(meta.description if meta.description is not None else (bundle.get("description") or ""))[:MAX_DESCRIPTION_CHARS],
            asset_kind=summary.kind,
            extra={},
            created_at=now,
        )
        db.add(item)
        db.flush()
        tags = meta.tags if meta.tags is not None else parse_tags(list(bundle.get("tags") or [])) or []
        set_tags(db, item, tags)
        item.search_text = search_text(item.title, item.summary, tags, bundle.get("prompt") or "", item.slug)
    elif item.owner_id != user.id:
        raise ApiError(403, "not_owner")
    elif item.asset_kind != summary.kind:
        raise ApiError(422, "asset_kind_changed", kind=item.asset_kind)
    else:
        update_metadata(ctx, db, item, user, meta, None)
    number = _next_number(db, item)
    version = ItemVersion(
        item_id=item.id,
        number=number,
        version=str(number),
        status=VERSION_PENDING if summary.real_person else VERSION_APPROVED,
        submitter_id=user.id,
        file_sha256=sha256_hex(json.dumps(bundle, sort_keys=True, ensure_ascii=False).encode("utf-8")),
        file_size=0,
        meta={"bundle": bundle, "consent_kind": consent},
        changelog=meta.changelog[:MAX_CHANGELOG_CHARS],
        reviewed_at=None if summary.real_person else now,
        created_at=now,
    )
    db.add(version)
    db.flush()
    if not summary.real_person:
        publish_version(item, version)
    elif item.current_version_id is None:
        # 还没有公开的版本:列表页不显示它,但作者自己的「我的提交」要有封面和种类。
        item.cover_sha256 = summary.cover_sha256 or None
    db.flush()
    log_event(logger, "asset submitted", item_id=item.id, version=version.number, user_id=user.id, pending=summary.real_person)
    return item, version


def asset_media(ctx: Context, db: Session, bundle: dict, *, absolute: bool = False) -> dict[str, dict]:
    """分享包里每张参考图的地址。下载、详情、审核队列给的都是它。

    `absolute`:下载给的是**完整地址**。本地存储出的是站内相对路径(官网同源,直接能用),而下载的一方是
    桌面应用,它不在这个站点上。
    """
    hashes = [ref["sha256"] for ref in bundle.get("references") or []]
    for variant in bundle.get("variants") or []:
        hashes.extend(ref["sha256"] for ref in variant.get("references") or [])
    if not hashes:
        return {}
    def url_of(blob: Blob) -> str:
        url = ctx.storage.media_url(blob.storage_key)
        return f"{ctx.settings.public_url}{url}" if absolute and url.startswith("/") else url

    return {
        blob.sha256: {"url": url_of(blob), "content_type": blob.content_type, "size": blob.size}
        for blob in db.scalars(select(Blob).where(Blob.sha256.in_(set(hashes))))
    }


# ---------------- 审核 ----------------


def previous_approved(db: Session, version: ItemVersion) -> ItemVersion | None:
    return db.scalars(
        select(ItemVersion)
        .where(
            ItemVersion.item_id == version.item_id,
            ItemVersion.status == VERSION_APPROVED,
            ItemVersion.number < version.number,
        )
        .order_by(ItemVersion.number.desc())
        .limit(1)
    ).first()


def _dict_diff(old: dict, new: dict) -> dict:
    added = {key: new[key] for key in new.keys() - old.keys()}
    removed = {key: old[key] for key in old.keys() - new.keys()}
    changed = {key: {"from": old[key], "to": new[key]} for key in old.keys() & new.keys() if old[key] != new[key]}
    return {"added": added, "removed": removed, "changed": changed}


def plugin_diff(current: ItemVersion, previous: ItemVersion | None) -> dict:
    """审核界面并排看的东西:清单、权限、工具、文件列表,与上一个通过的版本比。"""
    new_meta = current.meta or {}
    old_meta = (previous.meta or {}) if previous is not None else {}
    new_manifest = new_meta.get("manifest") or {}
    old_manifest = old_meta.get("manifest") or {}
    new_perms = set(new_manifest.get("permissions") or [])
    old_perms = set(old_manifest.get("permissions") or [])
    new_tools = {tool["name"]: tool for tool in (new_meta.get("index_entry") or {}).get("tools", [])}
    old_tools = {tool["name"]: tool for tool in (old_meta.get("index_entry") or {}).get("tools", [])}
    new_files = {one["path"]: one for one in new_meta.get("files") or []}
    old_files = {one["path"]: one for one in old_meta.get("files") or []}
    return {
        "previous_version": previous.version if previous is not None else None,
        "manifest": _dict_diff(old_manifest, new_manifest),
        "permissions": {"added": sorted(new_perms - old_perms), "removed": sorted(old_perms - new_perms)},
        "tools": {
            "added": sorted(new_tools.keys() - old_tools.keys()),
            "removed": sorted(old_tools.keys() - new_tools.keys()),
            "effects_changed": sorted(
                name for name in new_tools.keys() & old_tools.keys()
                if new_tools[name].get("effects") != old_tools[name].get("effects")
            ),
        },
        "files": {
            "added": sorted(new_files.keys() - old_files.keys()),
            "removed": sorted(old_files.keys() - new_files.keys()),
            "changed": sorted(
                path for path in new_files.keys() & old_files.keys() if new_files[path]["sha256"] != old_files[path]["sha256"]
            ),
        },
    }


def review(db: Session, version: ItemVersion, reviewer: User, *, approve: bool, note: str = "") -> Item:
    if version.status != VERSION_PENDING:
        raise ApiError(409, "submission_not_pending")
    item = db.get(Item, version.item_id)
    assert item is not None
    version.status = VERSION_APPROVED if approve else VERSION_REJECTED
    version.review_note = note[:MAX_CHANGELOG_CHARS]
    version.reviewed_by = reviewer.id
    version.reviewed_at = utcnow()
    if approve:
        current = db.get(ItemVersion, item.current_version_id) if item.current_version_id else None
        if current is None or versions.compare(version.version, current.version) in (1, None):
            publish_version(item, version)
    log_event(logger, "submission reviewed", version_id=version.id, approved=approve, reviewer_id=reviewer.id)
    return item


__all__ = [
    "Metadata",
    "asset_media",
    "read_asset",
    "submit_asset",
    "parse_tags",
    "plugin_diff",
    "previous_approved",
    "publish_version",
    "read_plugin",
    "read_workflow",
    "review",
    "search_text",
    "set_tags",
    "sniff_image",
    "store_blob",
    "store_cover",
    "submit_plugin",
    "submit_workflow",
    "unique_slug",
    "update_metadata",
]
