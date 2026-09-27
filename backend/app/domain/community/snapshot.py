"""画板 → 一份可以分享出去的快照(`mosael.board-snapshot/1`,ADR 0026「快照格式」)。

## 带什么、不带什么

快照里的一格和本机画布上的一格**同形**,但只带**看得见的内容**。判据是白名单,不是黑名单:
每种格子带哪几个字段在下面写死,别的一概不带 —— 画布上以后长出一个新字段(新的运行态、新的连接 id),
它不会因为「忘了加进黑名单」就被分享出去。

- 都带:`id`、`kind`、`x`、`y`、`width`、`height`、`title`;
- 便签:`text`、`text_format`、`color`;分组框:`color`;
- 图片 / 视频 / 音频:`media`(原文件的 sha256 + 类型 + 尺寸,图片视频再带一张缩略图的 sha256)、
  生成它的**提示词**(`prompt`,ADR:提示词以外的生成参数一概不带);
- 文档:钉住那一版的 `markdown` 和 `revision`;
- 3D 场景:`preview`(预览图,和媒体同形);
- 资产格(ADR 0027):像一张图片格那样带**封面**(`media`),`title` 缺省是资产的名字,`entity_kind` 是
  人物 / 场景 / 道具 —— 查看页照图片画、角上标种类。资产本身(提示词描述、其余参考图、音色)不带:
  分享资产是另一件事(ADR 0027 §4)。

**不带**:`run`(运行态、任务 id)、`form` 里除提示词以外的一切(供应商连接 id、模型、参数、绑定、
能力设置 —— 其中可能有密钥)、`asset_id` / `note_id` / `scene_id` 这些本机 id、本机路径、标记。

## 文件

媒体按**内容哈希**引用,文件单独上传(见 shares):同一份素材在板上摆两次只传一次,再分享一版时
服务端已经有的也不再传。
"""

from __future__ import annotations

import hashlib
import mimetypes
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, Board, Entity
from app.domain.boards.canvas import DEFAULT_SIZE
from app.domain.community.errors import TooLarge
from app.media.paths import resolve_key
from app.media.thumbnails import THUMBNAIL_MEDIA_TYPE, generate_thumbnail, thumbnail_path

SCHEMA = "mosael.board-snapshot/1"

#: 限额(ADR 0026 §5)。服务端照样会拦;这里先拦,是为了在传了几百兆之后才被拒之前就说清楚。
MAX_ITEMS = 300
MAX_FILE_BYTES = 200 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024

_MEDIA_KINDS = ("image", "video", "audio")
#: 这几种有缩略图(音频没有画面)。
_THUMBNAIL_KINDS = ("image", "video")
_HASH_CHUNK = 1024 * 1024


@dataclass(frozen=True)
class SnapshotFile:
    sha256: str
    size: int
    content_type: str
    path: Path


@dataclass(frozen=True)
class Snapshot:
    body: dict[str, Any]
    files: tuple[SnapshotFile, ...]


@dataclass(frozen=True)
class _Source:
    """一格引用的一份文件:哪一格、哪份素材、盘上在哪。"""

    item_id: str
    asset: Asset
    path: Path


def _items(board: Board) -> list[dict[str, Any]]:
    return [item for item in (board.canvas or {}).get("items") or [] if isinstance(item, dict)]


def _entities(db: Session, board: Board) -> dict[str, tuple[Entity, str | None]]:
    """板上资产格引用的资产(这个工作区里还在的),连同它的封面素材 id(没设封面就是第一张参考图)。"""
    from app.domain.entities import counts_for, cover_of

    wanted = {str(item["entity_id"]) for item in _items(board)
              if item.get("kind") == "entity" and isinstance(item.get("entity_id"), str)}
    if not wanted:
        return {}
    rows = list(db.scalars(select(Entity).where(Entity.id.in_(wanted), Entity.workspace_id == board.workspace_id)))
    _refs, _variants, first = counts_for(db, [row.id for row in rows])
    return {row.id: (row, cover_of(row, first.get(row.id))) for row in rows}


def _asset_of(item: dict[str, Any], entities: dict[str, tuple[Entity, str | None]]) -> str:
    """这一格画的是哪份素材:媒体格和 3D 场景格是它的 `asset_id`,资产格是资产的封面。"""
    if item.get("kind") == "entity":
        found = entities.get(str(item.get("entity_id") or ""))
        return str(found[1] or "") if found else ""
    return str(item.get("asset_id") or "") if isinstance(item.get("asset_id"), str) else ""


def _sources(db: Session, board: Board) -> list[_Source]:
    """板上每一格引用的、**这个工作区里、盘上真有文件**的那份素材。

    文件没了(素材删了、还在生成)的格子照样进快照,只是没有媒体 —— 和本机画布上的空槽一个样子。
    """
    entities = _entities(db, board)
    wanted = {
        _asset_of(item, entities)
        for item in _items(board)
        if item.get("kind") in (*_MEDIA_KINDS, "scene", "entity")
    } - {""}
    if not wanted:
        return []
    assets = {
        asset.id: asset
        for asset in db.scalars(select(Asset).where(Asset.id.in_(wanted), Asset.workspace_id == board.workspace_id))
    }
    found: list[_Source] = []
    for item in _items(board):
        if item.get("kind") not in (*_MEDIA_KINDS, "scene", "entity"):
            continue
        asset = assets.get(_asset_of(item, entities))
        if asset is None or not asset.file_key:
            continue
        path = resolve_key(asset.file_key)
        if path.is_file():
            found.append(_Source(item_id=str(item["id"]), asset=asset, path=path))
    return found


def _megabytes(size: int) -> str:
    return f"{size / (1024 * 1024):.0f}"


def check_limits(db: Session, board: Board) -> None:
    """**只看大小、不算哈希**的那一遍检查:点「生成链接」的那一刻就要能说「超了」。超了抛 TooLarge。"""
    count = len(_items(board))
    if count > MAX_ITEMS:
        raise TooLarge("communityErr_tooManyItems", count=count, limit=MAX_ITEMS)
    total = 0
    seen: set[Path] = set()
    for source in _sources(db, board):
        if source.path in seen:
            continue
        seen.add(source.path)
        size = source.path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise TooLarge(
                "communityErr_fileTooLarge", name=source.asset.name, size=_megabytes(size), limit=_megabytes(MAX_FILE_BYTES)
            )
        total += size
    if total > MAX_TOTAL_BYTES:
        raise TooLarge("communityErr_totalTooLarge", size=_megabytes(total), limit=_megabytes(MAX_TOTAL_BYTES))


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(_HASH_CHUNK):
            digest.update(block)
    return digest.hexdigest()


def _content_type(path: Path, fallback: str = "application/octet-stream") -> str:
    return mimetypes.guess_type(path.name)[0] or fallback


class _Files:
    """快照要上传的文件,按哈希去重。"""

    def __init__(self) -> None:
        self.by_hash: dict[str, SnapshotFile] = {}

    def add(self, path: Path, content_type: str) -> SnapshotFile:
        digest = sha256_of(path)
        known = self.by_hash.get(digest)
        if known is not None:
            return known
        entry = SnapshotFile(sha256=digest, size=path.stat().st_size, content_type=content_type, path=path)
        self.by_hash[digest] = entry
        return entry


def _thumbnail(source: _Source, files: _Files) -> str | None:
    """这份素材的缩略图(和素材库里用的是同一张;没有就现做一张,做不出来就不带)。"""
    if source.asset.kind not in _THUMBNAIL_KINDS:
        return None
    directory = source.path.parent
    thumb = thumbnail_path(directory)
    if not thumb.is_file():
        generate_thumbnail(source.path, source.asset.kind, directory)
    if not thumb.is_file():
        return None
    return files.add(thumb, THUMBNAIL_MEDIA_TYPE).sha256


def _media(source: _Source, files: _Files, *, with_thumbnail: bool) -> dict[str, Any]:
    original = files.add(source.path, _content_type(source.path))
    media: dict[str, Any] = {"sha256": original.sha256, "content_type": original.content_type}
    info = source.asset.media_info or {}
    for field in ("width", "height"):
        value = info.get(field)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
            media[field] = int(value)
    if with_thumbnail:
        thumb = _thumbnail(source, files)
        if thumb:
            media["thumb_sha256"] = thumb
    return media


def _document(db: Session, board: Board, item: dict[str, Any]) -> dict[str, Any]:
    """文档格钉住的那一版正文。笔记删了、进了回收站、那一版找不到:只带标题,正文留空 —— 不猜成最新版。"""
    from app.domain.notes import NoteDomainError, read_reference

    note_id, revision = item.get("note_id"), item.get("note_revision")
    if not isinstance(note_id, str) or not isinstance(revision, int):
        return {"markdown": ""}
    try:
        reference = read_reference(db, board.workspace_id, note_id, revision)
    except NoteDomainError:
        return {"markdown": ""}
    out: dict[str, Any] = {"markdown": str(reference.get("markdown") or ""), "revision": int(reference["revision"])}
    if not item.get("title") and reference.get("title"):
        out["title"] = str(reference["title"])[:120]
    return out


#: 快照里 id 的字符集(ADR 0026 快照格式;社区服务那一侧由 mosael-formats 的 board_snapshot 校验)。
#: 本机画布上的 id 更宽松 —— 连线缺省的 id 是 `源->目标`,带着 `>` —— 不合的换成按位置编的名字。
_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _snapshot_ids(raw: list[Any], prefix: str) -> list[str]:
    """每一项在快照里的 id:合规的原样留着,不合的(或和别人撞了的)换成 `<前缀><序号>`。"""
    taken: set[str] = set()
    out: list[str] = []
    for index, entry in enumerate(raw):
        wanted = str(entry.get("id") or "") if isinstance(entry, dict) else ""
        if not _ID_RE.match(wanted) or wanted in taken:
            wanted = f"{prefix}{index}"
            while wanted in taken:
                wanted = f"{wanted}_"
        taken.add(wanted)
        out.append(wanted)
    return out


def _base(item: dict[str, Any], snapshot_id: str) -> dict[str, Any]:
    kind = str(item["kind"])
    default_width, default_height = DEFAULT_SIZE.get(kind, (240, 160))
    out: dict[str, Any] = {
        "id": snapshot_id,
        "kind": kind,
        "x": float(item["x"]),
        "y": float(item["y"]),
        "width": float(item.get("width") or default_width),
        "height": float(item.get("height") or default_height),
    }
    if isinstance(item.get("title"), str) and item["title"]:
        out["title"] = item["title"]
    return out


def build(db: Session, board: Board, *, on_progress: Callable[[float], None] | None = None) -> Snapshot:
    """算出快照和要传的文件。会读每个文件算哈希、缺缩略图时现做 —— 在任务里跑,不在请求里跑。"""
    check_limits(db, board)
    sources = {source.item_id: source for source in _sources(db, board)}
    entities = _entities(db, board)
    files = _Files()
    items: list[dict[str, Any]] = []
    raw_items = _items(board)
    item_ids = _snapshot_ids(raw_items, "i")
    renamed = {str(item["id"]): new for item, new in zip(raw_items, item_ids)}
    for index, item in enumerate(raw_items):
        kind = str(item.get("kind") or "")
        out = _base(item, item_ids[index])
        if kind == "note":
            for field in ("text", "text_format", "color"):
                if isinstance(item.get(field), str):
                    out[field] = item[field]
        elif kind == "frame":
            if isinstance(item.get("color"), str):
                out["color"] = item["color"]
        elif kind in _MEDIA_KINDS:
            source = sources.get(str(item["id"]))
            if source is not None:
                out["media"] = _media(source, files, with_thumbnail=kind in _THUMBNAIL_KINDS)
            prompt = (item.get("form") or {}).get("prompt") if isinstance(item.get("form"), dict) else None
            if isinstance(prompt, str) and prompt.strip():
                out["prompt"] = prompt
        elif kind == "document":
            out.update(_document(db, board, item))
        elif kind == "scene":
            source = sources.get(str(item["id"]))
            if source is not None:
                out["preview"] = _media(source, files, with_thumbnail=True)
        elif kind == "entity":
            found = entities.get(str(item.get("entity_id") or ""))
            if found is not None:
                entity = found[0]
                out["entity_kind"] = entity.kind
                if "title" not in out:
                    out["title"] = entity.name[:120]
            source = sources.get(str(item["id"]))
            if source is not None:
                out["media"] = _media(source, files, with_thumbnail=True)
        items.append(out)
        if on_progress is not None and raw_items:
            on_progress((index + 1) / len(raw_items))
    raw_edges = [edge for edge in (board.canvas or {}).get("edges") or []
                 if isinstance(edge, dict) and edge.get("source") in renamed and edge.get("target") in renamed]
    edges = []
    for edge, edge_id in zip(raw_edges, _snapshot_ids(raw_edges, "e")):
        out_edge = {"id": edge_id, "source": renamed[edge["source"]], "target": renamed[edge["target"]]}
        if isinstance(edge.get("label"), str) and edge["label"]:
            out_edge["label"] = edge["label"]
        edges.append(out_edge)
    body = {"schema": SCHEMA, "viewport": {"x": 0, "y": 0, "zoom": 1}, "items": items, "edges": edges}
    snapshot = Snapshot(body=body, files=tuple(files.by_hash.values()))
    total = sum(one.size for one in snapshot.files)
    if total > MAX_TOTAL_BYTES:
        raise TooLarge("communityErr_totalTooLarge", size=_megabytes(total), limit=_megabytes(MAX_TOTAL_BYTES))
    return snapshot
