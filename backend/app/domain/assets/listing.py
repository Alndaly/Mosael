"""素材库的列表:**服务端**筛选、排序、按游标分页,以及页签上那几个数。

此前 `GET /api/assets` 一次交回整个工作区的每一份素材(连同完整的 media_info),筛选、排序、
计数全在浏览器里做。一千二百份素材是将近 1 MB 的 JSON,素材页把它们一次全画出来 —— 打开要好几秒,
而人一眼看得见的只有十几张。现在:

- 列表一页一页地给(`page`),筛选和排序在这里做,游标认的是「上一页最后那一份」;
- 页签上的数字和标签筛选的候选另取(`facets`),它们说的是整个范围,不跟着这一页走;
- 中间产物(逐句配音的一句……,见 domain/assets/intermediates)默认不列,点名那一种才列 —— 素材库是给人找东西的,
  工序的零件在时间线上照常用,不必摊在这里。

游标是「排序键 + id」(keyset),不是偏移量:翻到一半有人导入了新素材,偏移量会让页边上的那一份
重复或漏掉,游标不会。排序键相同的几份(同一时刻导入的一批)按 id 定先后,所以翻页是稳定的。
"""

from __future__ import annotations

import base64
import binascii
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, and_, exists, func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import Asset
from app.domain.assets.intermediates import INTERMEDIATE_KINDS

#: 一页默认几份:素材页一屏放得下十几张卡片,多取几行好让往下滚的时候不必马上等下一页。
DEFAULT_PAGE_SIZE = 60
MAX_PAGE_SIZE = 200

#: 排序:界面上的「最新导入 / 最近修改 / 名称 / 时长」。
SORTS = ("created", "updated", "name", "duration")
TAG_MATCHES = ("all", "any")


class AssetListingError(LocalizedError, ValueError):
    """列表请求本身不对:游标不是这份列表发的、排序不认得。"""

    status = 422


@dataclass(frozen=True)
class AssetScope:
    """看哪些素材:一个工作区(可选再限定到一个项目)里,满足这些条件的。"""

    workspace_id: str
    #: 给了就是「这个项目里的 + 工作区级的」—— 工作区级素材属于整个工作区,任何项目都该能用它。
    project_id: str | None = None
    kinds: Sequence[str] = ()
    source: str | None = None
    #: 名字、原始文件名、标签里含这几个字(不分大小写)。
    query: str = ""
    tags: Sequence[str] = ()
    #: 勾了几个标签时:同时带有(all)/ 带有任一(any)。
    tag_match: str = "all"
    #: 看素材库(空串)还是某一种中间产物(见 domain/assets/intermediates)。
    intermediate: str = ""


@dataclass(frozen=True)
class AssetPage:
    items: list[Asset]
    #: 下一页从哪接着;None 就是到头了。
    next_cursor: str | None
    #: 满足条件的一共几份(不只是这一页)。
    total: int


@dataclass(frozen=True)
class AssetFacets:
    total: int
    kinds: dict[str, int] = field(default_factory=dict)
    tags: dict[str, int] = field(default_factory=dict)
    #: 每种中间产物各几份(整个范围的,不管眼下看的是哪一种)—— 素材页切过去的入口上写着它。
    intermediates: dict[str, int] = field(default_factory=dict)


def page(
    db: Session,
    scope: AssetScope,
    *,
    sort: str = "created",
    cursor: str | None = None,
    limit: int = DEFAULT_PAGE_SIZE,
) -> AssetPage:
    if sort not in SORTS:
        raise AssetListingError("assetErr_unknownSort", sort=sort)
    _check(scope)
    key, descending = _sort_key(sort)
    conditions = _conditions(scope)
    total = db.scalar(select(func.count()).select_from(Asset).where(*conditions)) or 0

    stmt = select(Asset, key).where(*conditions)
    if cursor:
        value, last_id = _decode(cursor, sort)
        after = tuple_(key, Asset.id) < tuple_(value, last_id) if descending else tuple_(key, Asset.id) > tuple_(value, last_id)
        stmt = stmt.where(after)
    order = (key.desc(), Asset.id.desc()) if descending else (key.asc(), Asset.id.asc())
    rows = db.execute(stmt.order_by(*order).limit(limit + 1)).all()
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _encode(sort, rows[-1][1], rows[-1][0].id) if more and rows else None
    return AssetPage(items=[row[0] for row in rows], next_cursor=next_cursor, total=total)


def facets(db: Session, workspace_id: str, *, project_id: str | None = None, intermediate: str = "") -> AssetFacets:
    """页签上的数字和标签筛选的候选:说的是**整个范围**(素材库,或点名的那一种中间产物),不看搜索词、
    不看勾了哪些标签 —— 和此前在浏览器里数全部素材是同一个答案。另交回每种中间产物各几份。"""
    scope = AssetScope(workspace_id=workspace_id, project_id=project_id, intermediate=intermediate)
    _check(scope)
    conditions = _conditions(scope)
    kinds = {kind: count for kind, count in db.execute(
        select(Asset.kind, func.count()).where(*conditions).group_by(Asset.kind))}
    tags: Counter[str] = Counter()
    for tagged in db.scalars(select(Asset.tags).where(*conditions)):
        tags.update(tag for tag in tagged or [] if isinstance(tag, str) and tag)
    whole = _range(AssetScope(workspace_id=workspace_id, project_id=project_id))
    intermediates = {kind: count for kind, count in db.execute(
        select(Asset.intermediate, func.count()).where(*whole, Asset.intermediate != "").group_by(Asset.intermediate))}
    return AssetFacets(total=sum(kinds.values()), kinds=kinds, tags=dict(tags), intermediates=intermediates)


def _check(scope: AssetScope) -> None:
    if scope.tag_match not in TAG_MATCHES:
        raise AssetListingError("assetErr_unknownTagMatch", match=scope.tag_match)
    if scope.intermediate and scope.intermediate not in INTERMEDIATE_KINDS:
        raise AssetListingError("assetErr_unknownIntermediate", kind=scope.intermediate)


def _range(scope: AssetScope) -> list[ColumnElement[bool]]:
    """看的是哪片:这个工作区(可选再限定到一个项目 —— 连同工作区级素材)。"""
    conditions: list[ColumnElement[bool]] = [Asset.workspace_id == scope.workspace_id]
    if scope.project_id:
        conditions.append(or_(Asset.project_id == scope.project_id, Asset.project_id.is_(None)))
    return conditions


def _conditions(scope: AssetScope) -> list[ColumnElement[bool]]:
    conditions = [*_range(scope), Asset.intermediate == scope.intermediate]
    if scope.kinds:
        conditions.append(Asset.kind.in_(list(scope.kinds)))
    if scope.source:
        conditions.append(Asset.source == scope.source)
    needle = scope.query.strip().lower()
    if needle:
        conditions.append(or_(
            func.lower(Asset.name).contains(needle, autoescape=True),
            func.lower(Asset.original_filename).contains(needle, autoescape=True),
            _any_tag(lambda tag: func.lower(tag).contains(needle, autoescape=True)),
            #: 逐句配音的一句名字都一样(「某某音色 · 配音」),认得出它的是念的那句话。
            func.lower(func.json_extract(Asset.media_info, "$.dub_line.text")).contains(needle, autoescape=True),
        ))
    wanted = [tag for tag in scope.tags if tag]
    if wanted:
        if scope.tag_match == "any":
            conditions.append(_any_tag(lambda tag: tag.in_(wanted)))
        else:
            conditions.append(and_(*(_any_tag(lambda tag, one=one: tag == one) for one in wanted)))
    return conditions


def _any_tag(test) -> ColumnElement[bool]:
    """这份素材的标签里有一个满足 `test`(标签是 JSON 数组,逐个展开来比)。"""
    each = func.json_each(Asset.tags).table_valued("value")
    return exists(select(1).select_from(each).where(test(each.c.value)))


def _sort_key(sort: str) -> tuple[ColumnElement[Any], bool]:
    """排序键和方向。名字不分大小写升序;时长没有的当 0,排在最后。"""
    if sort == "name":
        return func.lower(Asset.name), False
    if sort == "duration":
        return func.coalesce(func.json_extract(Asset.media_info, "$.duration"), 0.0), True
    if sort == "updated":
        return Asset.updated_at, True
    return Asset.created_at, True


def _encode(sort: str, value: Any, asset_id: str) -> str:
    if isinstance(value, datetime):
        value = value.isoformat()
    raw = json.dumps([sort, value, asset_id], ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode(cursor: str, sort: str) -> tuple[Any, str]:
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
        made_for, value, asset_id = json.loads(raw)
    except (ValueError, TypeError, binascii.Error):
        raise AssetListingError("assetErr_badCursor") from None
    #: 游标只对发它的那种排序有效:按时间排的游标拿去按名字翻,翻出来的是错乱的一页。
    if made_for != sort or not isinstance(asset_id, str):
        raise AssetListingError("assetErr_badCursor")
    if sort in ("created", "updated"):
        try:
            value = datetime.fromisoformat(str(value))
        except ValueError:
            raise AssetListingError("assetErr_badCursor") from None
    return value, asset_id
