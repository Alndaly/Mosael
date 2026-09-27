"""游标分页:`?cursor=…&limit=…` → `{"items": […], "next_cursor": "…" | null}`。

游标是「上一页最后一行的排序键」(base64 的 JSON),按键集取下一页 —— 不用 offset:列表在翻页的同时
被插入新行时,offset 会重复或漏掉行,键集不会。排序一律降序,最后一列是 id(保证全序)。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, or_
from sqlalchemy.orm import Session

from community.crypto import b64url, b64url_decode
from community.errors import ApiError

DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, int(limit)))


def _encode_value(value: Any) -> Any:
    return {"$dt": value.isoformat()} if isinstance(value, datetime) else value


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict) and "$dt" in value:
        return datetime.fromisoformat(value["$dt"])
    return value


def encode_cursor(values: Sequence[Any]) -> str:
    return b64url(json.dumps([_encode_value(one) for one in values], separators=(",", ":")).encode("utf-8"))


def decode_cursor(cursor: str | None, width: int) -> list[Any] | None:
    if not cursor:
        return None
    try:
        values = json.loads(b64url_decode(cursor))
    except (ValueError, UnicodeDecodeError) as exc:
        raise ApiError(422, "invalid_request", fields="cursor") from exc
    if not isinstance(values, list) or len(values) != width:
        raise ApiError(422, "invalid_request", fields="cursor")
    try:
        return [_decode_value(one) for one in values]
    except (TypeError, ValueError) as exc:
        raise ApiError(422, "invalid_request", fields="cursor") from exc


def paginate(
    db: Session,
    stmt: Select,
    *,
    keys: Sequence[Any],
    cursor: str | None,
    limit: int | None,
    key_of: Callable[[Any], Sequence[Any]],
    scalars: bool = True,
) -> tuple[list[Any], str | None]:
    """按 `keys`(列,全部降序)做键集分页。`key_of(row)` 给出一行的排序键。"""
    size = clamp_limit(limit)
    after = decode_cursor(cursor, len(keys))
    if after is not None:
        # (k0 < v0) OR (k0 = v0 AND k1 < v1) OR …
        clauses = []
        for index in range(len(keys)):
            equal = [keys[j] == after[j] for j in range(index)]
            clauses.append(and_(*equal, keys[index] < after[index]))
        stmt = stmt.where(or_(*clauses))
    stmt = stmt.order_by(*[key.desc() for key in keys]).limit(size + 1)
    rows = list(db.scalars(stmt).all() if scalars else db.execute(stmt).all())
    next_cursor = encode_cursor(key_of(rows[size - 1])) if len(rows) > size else None
    return rows[:size], next_cursor


__all__ = ["DEFAULT_LIMIT", "MAX_LIMIT", "clamp_limit", "decode_cursor", "encode_cursor", "paginate"]
