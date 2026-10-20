"""游标分页:`?cursor=…&limit=…` → `{"items": […], "next_cursor": "…" | null}`。

游标是"上一页最后一行的排序键"(base64url 的 JSON),按键集取下一页 —— 不用 offset:列表在翻页
的同时被插入新行时,offset 会重复或漏掉行,键集不会。排序一律降序,最后一列是 id(保证全序)。
"""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import and_, or_

from cloud.errors import CloudError

DEFAULT_LIMIT = 20
MAX_LIMIT = 50


def clamp_limit(limit: int | None) -> int:
    if limit is None:
        return DEFAULT_LIMIT
    return max(1, min(MAX_LIMIT, int(limit)))


def _encode_value(value: Any) -> Any:
    return {"$dt": value.isoformat()} if isinstance(value, datetime) else value


def _decode_value(value: Any) -> Any:
    if isinstance(value, dict) and set(value) == {"$dt"}:
        return datetime.fromisoformat(value["$dt"])
    return value


def encode_cursor(values: Sequence[Any]) -> str:
    payload = json.dumps([_encode_value(one) for one in values], separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def decode_cursor(cursor: str | None, width: int) -> list[Any] | None:
    if not cursor:
        return None
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        values = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, UnicodeDecodeError, TypeError) as exc:
        raise CloudError(422, "invalid_cursor") from exc
    if not isinstance(values, list) or len(values) != width:
        raise CloudError(422, "invalid_cursor")
    try:
        return [_decode_value(one) for one in values]
    except (TypeError, ValueError) as exc:
        raise CloudError(422, "invalid_cursor") from exc


def after_clause(keys: Sequence[Any], values: Sequence[Any]):
    """`(k0 < v0) OR (k0 = v0 AND k1 < v1) OR …`,全部按键降序。"""
    clauses = [
        and_(*([keys[index] == values[index] for index in range(position)] + [keys[position] < values[position]]))
        for position in range(len(keys))
    ]
    return or_(*clauses)
