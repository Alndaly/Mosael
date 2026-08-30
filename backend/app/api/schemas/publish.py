"""Publishing domain request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.api.schemas.base import OrmModel


class PublishOptionChoice(BaseModel):
    value: str
    label: str


class PublishOptionSpec(BaseModel):
    """一个平台专属发布选项的声明。**前端照它渲染控件,后端照它校验** —— 只有这一份。"""

    key: str
    label: str
    type: Literal["enum", "bool"]
    default: Any
    choices: list[PublishOptionChoice] = Field(default_factory=list)
    description: str = ""


class PublishPlatformOut(BaseModel):
    platform: str
    label: str
    description: str
    config: dict
    title_max: int = 300
    short_title: bool = False
    #: 该平台自己的发布选项声明(可见性…)。前端照它渲染控件,别处不硬编码。
    options: list[PublishOptionSpec] = Field(default_factory=list)


class PublishAccountCreate(BaseModel):
    workspace_id: str
    platform: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    config: dict = Field(default_factory=dict)
    proxy: str | None = Field(default=None, max_length=300)


class PublishAccountUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=160)
    config: dict | None = None
    enabled: bool | None = None
    proxy: str | None = Field(default=None, max_length=300)


class PublishAccountOut(OrmModel):
    id: str
    workspace_id: str
    platform: str
    name: str
    config: dict
    enabled: bool
    proxy: str | None = None
    binding_status: str = "unknown"
    last_error: str | None = None
    last_checked_at: datetime | None = None
    profile_name: str | None = None
    created_at: datetime


class PublishCreate(BaseModel):
    workspace_id: str
    account_id: str
    asset_id: str
    title: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=24)
    short_title: str = Field(default="", max_length=80)
    options: dict[str, Any] = Field(default_factory=dict)


class PublishTaskOut(BaseModel):
    id: str
    workspace_id: str
    account_id: str
    account_name: str
    platform: str
    asset_id: str
    asset_name: str
    title: str
    description: str
    tags: list[str]
    status: str
    error: str | None
    result: dict
    job_id: str | None
    created_at: datetime


class PublishCopyRequest(BaseModel):
    workspace_id: str
    asset_id: str | None = None
    brief: str = Field(default="", max_length=2000)
    profile_id: str | None = None


class PublishCopyResponse(BaseModel):
    title: str
    description: str
    tags: list[str]
