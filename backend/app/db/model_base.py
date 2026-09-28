"""Shared ORM construction primitives used by domain-owned model slices."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    """朴素 UTC 时间戳:ORM 列的默认值,迁移里补时间也用它。

    `datetime.utcnow()` 自 Python 3.12 起已废弃(3.15 计划移除),这里是等价写法:
    `datetime.now(UTC)` 再摘掉 tzinfo —— 值一模一样,库里已有的行不受影响。
    """
    return datetime.now(UTC).replace(tzinfo=None)
