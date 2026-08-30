"""Shared ORM construction primitives used by domain-owned model slices."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
