"""画板快照(`schema: "mosael.board-snapshot/1"`)的校验。见 ADR 0026 的「快照格式」。

快照 = 画布的格子与连线(去掉运行态、任务 id、连接 id 这类本机事实)+ 格子引用的媒体文件(**只以内容
哈希引用**)+ 文档格钉住那一版的正文。桌面端生成它,社区服务收它、原样交给只读查看页。

格子与本机画布的格子同形,种类会随应用增加,所以这里不列举格子种类、不逐字段定形;这里守的是
**会出事的那几条**:

- 顶层只有 `schema` / `viewport` / `items` / `edges` 四个键;
- 格子 id 不重复,坐标尺寸是有限的数,连线两端都是存在的格子;
- 媒体只能以 sha256 引用(任何名为 `sha256` 或以 `_sha256` 结尾的键),格式必须是 64 位小写十六进制
  —— 服务端据此核对「引用的每个文件都真的上传过」;
- 不许出现 `file:` 地址(本机路径不该跟着快照出门);
- 格子数有上限(由调用方给,社区服务可配置)。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

from mosael_formats.i18n import FormatError

SCHEMA = "mosael.board-snapshot/1"
TOP_LEVEL_KEYS = frozenset({"schema", "viewport", "items", "edges"})
DEFAULT_MAX_ITEMS = 300

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")

#: 一个格子里单个字符串的上限(文档格的正文最长)。
MAX_STRING_CHARS = 200_000
#: 嵌套深度上限:格子是画布数据,不是任意 JSON。
MAX_DEPTH = 12
_GEOMETRY_KEYS = ("x", "y", "width", "height")
_IMAGE_TYPES = ("image/",)


class SnapshotError(FormatError):
    """快照不合格式。"""


@dataclass(frozen=True)
class MediaRef:
    """快照里一个图像格的媒体引用(生成分享预览图用):原图与缩略图的哈希。"""

    item_id: str
    sha256: str
    thumb_sha256: str = ""
    content_type: str = ""


@dataclass(frozen=True)
class SnapshotSummary:
    item_count: int
    #: 引用到的全部文件哈希。
    hashes: frozenset[str] = frozenset()
    #: 图像格,按快照里的顺序。
    images: list[MediaRef] = field(default_factory=list)


def _fail(where: str, detail: str) -> SnapshotError:
    return SnapshotError("snapshotErr_invalid", where=where, detail=detail)


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _walk(value: Any, where: str, hashes: set[str], depth: int = 0) -> None:
    """走一遍格子里的任意值:收集哈希引用,挡住 file: 地址、非有限数、过深与过长。"""
    if depth > MAX_DEPTH:
        raise _fail(where, "too deep")
    if isinstance(value, dict):
        for key, one in value.items():
            if not isinstance(key, str):
                raise _fail(where, "non-string key")
            here = f"{where}.{key}"
            if key == "sha256" or key.endswith("_sha256"):
                if one is None or one == "":
                    continue
                if not isinstance(one, str) or not SHA256_RE.match(one):
                    raise _fail(here, "must be a lowercase hex sha256")
                hashes.add(one)
                continue
            _walk(one, here, hashes, depth + 1)
    elif isinstance(value, list):
        for index, one in enumerate(value):
            _walk(one, f"{where}[{index}]", hashes, depth + 1)
    elif isinstance(value, str):
        if len(value) > MAX_STRING_CHARS:
            raise _fail(where, "string too long")
        if value.strip().lower().startswith("file:"):
            raise _fail(where, "local file address")
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise _fail(where, "not a finite number")
    elif value is not None and not isinstance(value, (int, bool)):
        raise _fail(where, "unsupported value")


def validate_snapshot(snapshot: Any, *, max_items: int = DEFAULT_MAX_ITEMS) -> SnapshotSummary:
    """校验一份快照,返回它引用了哪些文件。不合格式抛 SnapshotError。"""
    if not isinstance(snapshot, dict):
        raise _fail("snapshot", "must be an object")
    extra = set(snapshot) - TOP_LEVEL_KEYS
    if extra:
        raise _fail("snapshot", "unknown keys: " + ", ".join(sorted(map(str, extra))))
    if snapshot.get("schema") != SCHEMA:
        raise _fail("schema", f"must be {SCHEMA}")
    viewport = snapshot.get("viewport")
    if not isinstance(viewport, dict):
        raise _fail("viewport", "must be an object")
    for key in ("x", "y", "zoom"):
        if not _finite_number(viewport.get(key)):
            raise _fail(f"viewport.{key}", "must be a finite number")
    if viewport["zoom"] <= 0:
        raise _fail("viewport.zoom", "must be positive")
    items = snapshot.get("items")
    edges = snapshot.get("edges")
    if not isinstance(items, list):
        raise _fail("items", "must be a list")
    if not isinstance(edges, list):
        raise _fail("edges", "must be a list")
    if len(items) > max_items:
        raise SnapshotError("snapshotErr_tooManyItems", count=len(items), limit=max_items)

    hashes: set[str] = set()
    ids: set[str] = set()
    images: list[MediaRef] = []
    for index, item in enumerate(items):
        where = f"items[{index}]"
        if not isinstance(item, dict):
            raise _fail(where, "must be an object")
        item_id = item.get("id")
        if not isinstance(item_id, str) or not ID_RE.match(item_id):
            raise _fail(f"{where}.id", "invalid id")
        if item_id in ids:
            raise _fail(f"{where}.id", f"duplicate id {item_id}")
        ids.add(item_id)
        kind = item.get("kind")
        if not isinstance(kind, str) or not KIND_RE.match(kind):
            raise _fail(f"{where}.kind", "invalid kind")
        for key in _GEOMETRY_KEYS:
            if key in item and not _finite_number(item[key]):
                raise _fail(f"{where}.{key}", "must be a finite number")
        _walk(item, where, hashes)
        media = item.get("media")
        if isinstance(media, dict) and isinstance(media.get("sha256"), str):
            content_type = str(media.get("content_type") or "")
            if kind == "image" or content_type.startswith(_IMAGE_TYPES):
                images.append(
                    MediaRef(
                        item_id=item_id,
                        sha256=media["sha256"],
                        thumb_sha256=str(media.get("thumb_sha256") or ""),
                        content_type=content_type,
                    )
                )

    edge_ids: set[str] = set()
    for index, edge in enumerate(edges):
        where = f"edges[{index}]"
        if not isinstance(edge, dict):
            raise _fail(where, "must be an object")
        edge_id = edge.get("id")
        if not isinstance(edge_id, str) or not ID_RE.match(edge_id) or edge_id in edge_ids:
            raise _fail(f"{where}.id", "invalid or duplicate id")
        edge_ids.add(edge_id)
        if edge.get("source") not in ids or edge.get("target") not in ids:
            raise _fail(where, "source and target must be items in this snapshot")
        _walk(edge, where, hashes)

    return SnapshotSummary(item_count=len(items), hashes=frozenset(hashes), images=images)


__all__ = [
    "DEFAULT_MAX_ITEMS",
    "MediaRef",
    "SCHEMA",
    "SHA256_RE",
    "SnapshotError",
    "SnapshotSummary",
    "validate_snapshot",
]
