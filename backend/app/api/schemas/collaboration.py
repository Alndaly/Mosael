from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


SubjectType = Literal["board", "workflow", "sequence", "asset"]


class ActorOut(BaseModel):
    id: str | None = None
    username: str = ""
    display_name: str = ""
    avatar_key: str = ""


class ActivityOut(BaseModel):
    id: str
    workspace_id: str
    actor_id: str | None = None
    actor: ActorOut | None = None
    action: str
    subject_type: str
    subject_id: str
    summary: str
    payload: dict = Field(default_factory=dict)
    created_at: datetime


class CommentCreate(BaseModel):
    workspace_id: str
    subject_type: SubjectType
    subject_id: str
    body: str = Field(min_length=1, max_length=5000)
    mentioned_user_ids: list[str] = Field(default_factory=list)


class CommentOut(BaseModel):
    id: str
    workspace_id: str
    subject_type: str
    subject_id: str
    author_id: str | None = None
    author: ActorOut | None = None
    body: str
    mentioned_user_ids: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ReviewCreate(BaseModel):
    workspace_id: str
    subject_type: SubjectType
    subject_id: str
    reviewer_id: str
    note: str = Field(default="", max_length=2000)


class ReviewDecision(BaseModel):
    status: Literal["approved", "changes_requested", "cancelled"]
    note: str = Field(default="", max_length=2000)


class ReviewOut(BaseModel):
    id: str
    workspace_id: str
    subject_type: str
    subject_id: str
    requested_by: str | None = None
    requester: ActorOut | None = None
    reviewer_id: str
    reviewer: ActorOut | None = None
    status: str
    note: str
    decision_note: str
    decided_by: str | None = None
    created_at: datetime
    decided_at: datetime | None = None
