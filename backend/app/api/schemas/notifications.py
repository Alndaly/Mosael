"""In-app notification request and response schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.api.schemas.base import OrmModel


class NotificationOut(OrmModel):
    id: str
    workspace_id: str
    type: str
    title: str
    body: str
    link: str | None
    payload: dict
    read_at: datetime | None
    created_at: datetime


class NotifyRequest(BaseModel):
    workspace_id: str
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(default="", max_length=2000)


class NotificationListOut(BaseModel):
    items: list[NotificationOut]
    unread: int
