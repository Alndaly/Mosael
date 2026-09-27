"""资产(人物 / 场景 / 道具)和社区之间:发布、导入、看有没有新版本(ADR 0027 §4)。

**发布**:把一个资产和它的变体做成分享包 `mosael.asset/1`(校验在 `mosael_formats.asset_bundle`,社区服务收的时候
过的是同一份),参考图走画板分享同一套三步上传(`shares.missing_files` / `shares.upload_file`),再
`POST /assets`(第一次)或 `POST /assets/{slug}/versions`(之后)。只带图片参考图和**能公开的**专有字段 ——
音色、授权声明原文、关联的 3D 场景 / 模型、本机 id 都不出门(格式包在任何一层见到都会拒)。

**真人人物**:本机的授权声明要是「本人」或「已获授权」,而且这一次发布时在弹窗里再确认一遍「已获得本人同意
公开」;提交时带上 `consent_kind`,社区那边先审核再上架。

**导入**:`GET /assets/{slug}/download` 拿分享包和每张图的地址,逐张下载、**按哈希核对**(地址指向哪里都一样:
对不上就不收),作为素材导入工作区,再建资产、变体、角度和封面。导入的真人人物,授权声明记成「待你确认」
(catalog.CONSENT_PENDING)—— 别人声明过,这台机器上还没有人确认过,在那之前不能用于数字人。
导入**不要求连社区账号**:公开的东西谁都能拿。
"""

from __future__ import annotations

import hashlib
import logging
import mimetypes
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx
from mosael_formats import asset_bundle
from mosael_formats.i18n import FormatError
from sqlalchemy.orm import Session

from app.db.models import Entity
from app.domain import deployment
from app.domain.assets.importer import import_binary_asset
from app.domain.community import shares, transport
from app.domain.community.accounts import CommunityClient, read_json
from app.domain.community.errors import CommunityError, NotConfigured, Unreachable
from app.domain.community.snapshot import SnapshotFile, sha256_of
from app.domain.entities import catalog, library
from app.media.paths import resolve_key

logger = logging.getLogger(__name__)

#: 分享包里一张参考图最大多少、一个资产合计多少(和社区服务的上传上限同一个量级,见 community 的 Settings)。
MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_TITLE_CHARS = 120
MAX_SUMMARY_CHARS = 300
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,159}$")
_DOWNLOAD_CHUNK = 1024 * 1024


# --- 做分享包 ---------------------------------------------------------------


def _public_attributes(entity: Entity, *, variant: bool) -> dict[str, Any]:
    """专有字段里能公开的那几项(asset_bundle.PUBLIC_ATTRIBUTES / VARIANT_ATTRIBUTES)。"""
    allowed = (asset_bundle.VARIANT_ATTRIBUTES if variant else asset_bundle.PUBLIC_ATTRIBUTES)[entity.kind]
    attributes = entity.attributes or {}
    out: dict[str, Any] = {}
    for key in allowed:
        if key == "real_person":
            out[key] = bool(attributes.get("real_person"))
        elif attributes.get(key):
            out[key] = attributes[key]
    return out


def _references(db: Session, entity: Entity, files: dict[str, SnapshotFile]) -> tuple[list[dict[str, Any]], str]:
    """这个资产的**图片**参考图(按墙上的顺序)→ 分享包里的 references 和封面哈希。

    视频参考在本机可以用来生成,分享包里只带图(asset_bundle.IMAGE_TYPES)。盘上找不到文件的跳过。
    """
    references: list[dict[str, Any]] = []
    cover = ""
    for reference, asset in library.references_of(db, entity.id):
        if asset.kind != "image" or not asset.file_key:
            continue
        path = resolve_key(asset.file_key)
        if not path.is_file():
            continue
        content_type = mimetypes.guess_type(path.name)[0] or ""
        if content_type not in asset_bundle.IMAGE_TYPES:
            continue
        digest = sha256_of(path)
        if digest in {one["sha256"] for one in references}:
            continue
        files.setdefault(
            digest, SnapshotFile(sha256=digest, size=path.stat().st_size, content_type=content_type, path=path)
        )
        info = asset.media_info or {}
        ref: dict[str, Any] = {"sha256": digest, "content_type": content_type, "role": reference.role}
        for key in ("width", "height"):
            if isinstance(info.get(key), int) and info[key] > 0:
                ref[key] = info[key]
        references.append(ref)
        if asset.id == entity.cover_asset_id:
            cover = digest
    return references, cover or (references[0]["sha256"] if references else "")


def build_bundle(db: Session, entity: Entity) -> tuple[dict[str, Any], list[SnapshotFile]]:
    """一个资产(母体)→ 分享包和要上传的文件。先用格式包自己验一遍:验不过的不往外发。"""
    files: dict[str, SnapshotFile] = {}
    references, cover = _references(db, entity, files)
    if not references:
        raise CommunityError("communityErr_assetNoImages")
    variants: list[dict[str, Any]] = []
    for variant in library.variants_of(db, entity.id):
        refs, variant_cover = _references(db, variant, files)
        if not refs:
            # 没有图的变体(只写了一段描述)不带:分享包里的变体是「另一套参考图」。
            continue
        variants.append(
            {
                "name": variant.name,
                "description": variant.description,
                "prompt": variant.prompt,
                "tags": list(variant.tags or []),
                "attributes": _public_attributes(variant, variant=True),
                "references": refs,
                "cover_sha256": variant_cover,
            }
        )
    bundle = {
        "schema": asset_bundle.SCHEMA,
        "kind": entity.kind,
        "name": entity.name,
        "description": entity.description,
        "prompt": entity.prompt,
        "tags": list(entity.tags or []),
        "attributes": _public_attributes(entity, variant=False),
        "references": references,
        "cover_sha256": cover,
        "variants": variants,
    }
    try:
        asset_bundle.validate_bundle(bundle)
    except FormatError as exc:
        raise CommunityError("communityErr_assetBundle", detail=str(exc)) from exc
    total = sum(one.size for one in files.values())
    if total > MAX_TOTAL_BYTES:
        raise CommunityError("communityErr_assetTooLarge", limit=MAX_TOTAL_BYTES // (1024 * 1024))
    return bundle, list(files.values())


# --- 发布 -------------------------------------------------------------------


def _consent_kind(entity: Entity, confirmed: bool) -> str | None:
    """真人人物要本机声明过本人 / 已获授权,并且这一次确认了「已获得本人同意公开」。虚构的不带。"""
    attributes = entity.attributes or {}
    if not attributes.get("real_person"):
        return None
    consent = attributes.get("consent") if isinstance(attributes.get("consent"), dict) else {}
    kind = consent.get("kind")
    if kind not in ("self", "authorized"):
        raise CommunityError("communityErr_assetNeedsConsent")
    if not confirmed:
        raise CommunityError("communityErr_assetConfirmPublication")
    return str(kind)


def publish_entity(
    db: Session,
    *,
    entity: Entity,
    user_id: str,
    consent_confirmed: bool,
    title: str = "",
    summary: str = "",
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """发一个资产(第一次)或它的新版本(之后)。回 `{slug, url, version, status}`。"""
    if entity.parent_id:
        raise CommunityError("communityErr_assetVariantAlone")
    consent_kind = _consent_kind(entity, consent_confirmed)
    client = CommunityClient.for_user(db, user_id)
    bundle, files = build_bundle(db, entity)
    by_hash = {one.sha256: one for one in files}
    for digest, target in shares.missing_files(client, files):
        shares.upload_file(client, by_hash[digest], target)
    body: dict[str, Any] = {"bundle": bundle}
    if consent_kind:
        body["consent_kind"] = consent_kind
    if title.strip():
        body["title"] = title.strip()[:MAX_TITLE_CHARS]
    if summary.strip():
        body["summary"] = summary.strip()[:MAX_SUMMARY_CHARS]
    if tags is not None:
        body["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()][:8]
    published = (entity.community or {}).get("published") or {}
    slug = str(published.get("slug") or "") if published.get("origin") == client.origin else ""
    result = client.call("POST", f"/assets/{slug}/versions" if slug else "/assets", json=body)
    submission = result.get("submission") if isinstance(result.get("submission"), dict) else {}
    slug = str(result.get("slug") or slug)
    if not slug:
        raise CommunityError("communityErr_badResponse")
    outcome = {
        "slug": slug,
        "url": transport.absolute(client.origin, f"/assets/{slug}"),
        "version": str(submission.get("version") or result.get("version") or ""),
        "status": str(submission.get("status") or result.get("status") or "approved"),
        "origin": client.origin,
    }
    entity.community = {**(entity.community or {}), "published": outcome}
    db.commit()
    logger.info("资产 %s 发到社区:%s(第 %s 版,%s)", entity.id, slug, outcome["version"], outcome["status"])
    return outcome


# --- 导入 -------------------------------------------------------------------


def slug_of(link: str) -> str:
    """一个社区链接或 slug → slug。认 `…/assets/<slug>`(带不带语言段、带不带站点)和光秃秃的 slug。"""
    text = (link or "").strip()
    path = urlsplit(text).path if "://" in text else text
    parts = [part for part in path.split("/") if part]
    if "assets" in parts:
        index = parts.index("assets")
        parts = parts[index + 1 : index + 2]
    candidate = parts[-1].lower() if parts else ""
    if not _SLUG.match(candidate):
        raise CommunityError("communityErr_assetBadLink")
    return candidate


def _origin(db: Session) -> str:
    origin = deployment.community_url(db)
    if not origin:
        raise NotConfigured()
    return origin


def _public_get(origin: str, path: str, **params: Any) -> dict[str, Any]:
    """读社区上公开的东西,不带令牌(导入、浏览不需要连账号)。"""
    try:
        with transport.make_client() as http:
            response = http.get(transport.api_url(origin, path), params={k: v for k, v in params.items() if v})
    except httpx.HTTPError as exc:
        raise Unreachable(str(exc)) from exc
    return read_json(response)


def browse(db: Session, *, q: str = "", asset_kind: str = "", cursor: str = "") -> dict[str, Any]:
    """「从社区导入」弹窗里的列表:社区上公开的资产,图片地址补成完整的。"""
    origin = _origin(db)
    page = _public_get(origin, "/assets", q=q, asset_kind=asset_kind, cursor=cursor, limit=24)
    items = []
    for item in page.get("items") or []:
        if isinstance(item, dict):
            cover = item.get("cover_url")
            author = item.get("author") if isinstance(item.get("author"), dict) else {}
            items.append(
                {
                    **item,
                    "cover_url": transport.absolute(origin, str(cover)) if cover else None,
                    "author_name": str(author.get("display_name") or author.get("handle") or ""),
                }
            )
    return {"items": items, "next_cursor": page.get("next_cursor")}


def _download(url: str, expected: str) -> bytes:
    """下一张参考图,按哈希核对。地址是社区给的(本地存储或对象存储的预签名地址),不带令牌。"""
    digest = hashlib.sha256()
    chunks: list[bytes] = []
    size = 0
    try:
        with transport.make_client() as http, http.stream("GET", url) as response:
            if response.status_code >= 400:
                raise CommunityError("communityErr_assetDownload", status=response.status_code)
            for chunk in response.iter_bytes(_DOWNLOAD_CHUNK):
                size += len(chunk)
                if size > MAX_IMAGE_BYTES:
                    raise CommunityError("communityErr_assetTooLarge", limit=MAX_IMAGE_BYTES // (1024 * 1024))
                digest.update(chunk)
                chunks.append(chunk)
    except httpx.HTTPError as exc:
        raise Unreachable(str(exc)) from exc
    if digest.hexdigest() != expected:
        # 不管地址指向哪里:内容和分享包里说的那张对不上,就不收。
        raise CommunityError("communityErr_assetHashMismatch")
    return b"".join(chunks)


def _fetch_all(bundle: dict[str, Any], media: dict[str, Any]) -> dict[str, bytes]:
    """分享包里引用到的每一张图(母体和变体合起来,同一张只下一次),**全部**下载并核对完才往下走 ——
    中途哪张不对就什么都不建,不会留下半个资产。"""
    groups = [bundle.get("references") or [], *((one.get("references") or []) for one in bundle.get("variants") or [])]
    fetched: dict[str, bytes] = {}
    total = 0
    for references in groups:
        for ref in references:
            digest = ref["sha256"]
            if digest in fetched:
                continue
            source = media.get(digest) if isinstance(media.get(digest), dict) else {}
            url = str(source.get("url") or "")
            if not url.startswith(("http://", "https://")):
                raise CommunityError("communityErr_assetDownload", status=0)
            fetched[digest] = _download(url, digest)
            total += len(fetched[digest])
            if total > MAX_TOTAL_BYTES:
                raise CommunityError("communityErr_assetTooLarge", limit=MAX_TOTAL_BYTES // (1024 * 1024))
    return fetched


def _attach_references(
    db: Session,
    *,
    workspace_id: str,
    entity: Entity,
    references: list[dict[str, Any]],
    cover: str,
    fetched: dict[str, bytes],
    imported: dict[str, str],
) -> None:
    """把一组已经下载好的参考图导入成素材、挂到 `entity` 上(角度照分享包;同一张图在母体和变体里只导入一次)。"""
    for ref in references:
        digest = ref["sha256"]
        asset_id = imported.get(digest)
        if asset_id is None:
            extension = mimetypes.guess_extension(ref["content_type"]) or ".png"
            asset = import_binary_asset(
                db,
                workspace_id=workspace_id,
                project_id=None,
                data=fetched[digest],
                original=f"{entity.name}-{ref['role']}{extension}",
                content_type=ref["content_type"],
                source="community",
                name=f"{entity.name} · {ref['role']}",
            )
            asset_id = imported[digest] = asset.id
        library.add_reference(db, entity, asset_id, ref["role"], cover=digest == cover)


def import_asset(db: Session, *, workspace_id: str, user_id: str, link: str) -> Entity:
    """从社区导入一个资产(连同变体)到这个工作区。回新建的母体。"""
    origin = _origin(db)
    slug = slug_of(link)
    payload = _public_get(origin, f"/assets/{slug}/download")
    bundle = payload.get("bundle")
    try:
        summary = asset_bundle.validate_bundle(bundle)
    except FormatError as exc:
        raise CommunityError("communityErr_assetBundle", detail=str(exc)) from exc
    assert isinstance(bundle, dict)
    media = payload.get("media") if isinstance(payload.get("media"), dict) else {}
    fetched = _fetch_all(bundle, media)
    attributes = dict(bundle.get("attributes") or {})
    entity = library.create_entity(
        db,
        workspace_id=workspace_id,
        kind=summary.kind,
        name=bundle["name"],
        description=bundle.get("description") or "",
        prompt=bundle.get("prompt") or "",
        attributes=attributes,
        tags=list(bundle.get("tags") or []),
        actor_id=user_id,
    )
    if summary.real_person:
        # 别人声明过授权,这台机器上还没人确认过:在本机确认之前不能用于数字人(catalog.usable_for_digital_human)。
        entity.attributes = {
            **(entity.attributes or {}),
            "consent": {
                "kind": catalog.CONSENT_PENDING,
                "declared_by": "",
                "declared_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
            },
        }
    imported: dict[str, str] = {}
    _attach_references(
        db,
        workspace_id=workspace_id,
        entity=entity,
        references=bundle["references"],
        cover=bundle.get("cover_sha256") or "",
        fetched=fetched,
        imported=imported,
    )
    for variant in bundle.get("variants") or []:
        child = library.create_entity(
            db,
            workspace_id=workspace_id,
            kind=summary.kind,
            name=variant["name"],
            description=variant.get("description") or "",
            prompt=variant.get("prompt") or "",
            attributes=dict(variant.get("attributes") or {}),
            tags=list(variant.get("tags") or []),
            parent_id=entity.id,
            actor_id=user_id,
        )
        _attach_references(
            db,
            workspace_id=workspace_id,
            entity=child,
            references=variant.get("references") or [],
            cover=variant.get("cover_sha256") or "",
            fetched=fetched,
            imported=imported,
        )
    entity.community = {
        **(entity.community or {}),
        "source": {
            "slug": slug,
            "version": str(payload.get("version") or ""),
            "origin": origin,
            "url": transport.absolute(origin, f"/assets/{slug}"),
        },
    }
    db.commit()
    db.refresh(entity)
    logger.info("从社区导入资产 %s(%s,%s 张图)到工作区 %s", slug, summary.kind, len(imported), workspace_id)
    return entity


# --- 状态 -------------------------------------------------------------------


def status(db: Session, entity: Entity) -> dict[str, Any]:
    """资产详情里「社区」那一格:发出去的是哪一条、从哪一条导入的,以及那一条在社区上有没有新版本。

    查新版本读的是公开详情,不带令牌;社区连不上时照样回本机记着的那些,`latest` 为空。
    """
    community = dict(entity.community or {})
    source = community.get("source") if isinstance(community.get("source"), dict) else None
    out: dict[str, Any] = {"published": community.get("published"), "source": source, "latest_version": None}
    if source and source.get("slug") and source.get("origin"):
        try:
            detail = _public_get(str(source["origin"]), f"/assets/{source['slug']}")
        except CommunityError:
            return out
        out["latest_version"] = str(detail.get("version") or "") or None
    return out


__all__ = ["browse", "build_bundle", "import_asset", "publish_entity", "slug_of", "status"]
