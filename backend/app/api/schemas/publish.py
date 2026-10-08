"""Publishing domain request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from app.api.schemas.base import ApiModel, OrmModel


class PublishOptionChoice(ApiModel):
    value: str
    label: str


class PublishOptionSpec(ApiModel):
    """一个平台专属发布选项的声明。**前端照它渲染控件,后端照它校验** —— 只有这一份。"""

    key: str
    label: str
    type: Literal["enum", "bool"]
    default: Any
    choices: list[PublishOptionChoice] = Field(default_factory=list)
    description: str = ""


class PublishPlatformOut(ApiModel):
    platform: str
    label: str
    description: str
    config: dict
    title_max: int = 300
    short_title: bool = False
    #: 该平台自己的发布选项声明(可见性…)。前端照它渲染控件,别处不硬编码。
    options: list[PublishOptionSpec] = Field(default_factory=list)


class PublishAccountCreate(ApiModel):
    workspace_id: str
    platform: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=160)
    config: dict = Field(default_factory=dict)
    proxy: str | None = Field(default=None, max_length=300)


class PublishAccountUpdate(ApiModel):
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
    #: 存着的设置解不开了(主密钥换了或丢了):`config` 给空,界面说重新登录 / 重新填一次。此前 `config` 是 None,
    #: 整张账号列表 500,新建发布的目标下拉只写「没有匹配的结果」(体检 UM-22)。
    config_unreadable: bool = False
    enabled: bool
    proxy: str | None = None
    binding_status: str = "unknown"
    last_error: str | None = None
    last_checked_at: datetime | None = None
    created_at: datetime

    @field_validator("config", mode="before")
    @classmethod
    def _unreadable_config_is_empty(cls, value: Any) -> Any:
        return {} if value is None else value


class PublishCreate(ApiModel):
    workspace_id: str
    account_id: str
    asset_id: str
    title: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=24)
    short_title: str = Field(default="", max_length=80)
    options: dict[str, Any] = Field(default_factory=dict)


class PublishedPostOut(ApiModel):
    """发出去的那一条作品。`post_id` 为空说明发布时没从平台读到(不是没发出去)。"""

    platform: str
    post_id: str
    url: str
    ids: dict[str, str]
    published_at: str


class PublishTaskOut(ApiModel):
    id: str
    workspace_id: str
    account_id: str
    account_name: str
    platform: str
    #: 素材已经删了的那条发布记录为空(记录留着,见 db.model_slices.publish.PublishTask.asset_id)。
    asset_id: str | None
    asset_name: str
    title: str
    description: str
    tags: list[str]
    status: str
    error: str | None
    result: dict
    post: PublishedPostOut | None = None
    job_id: str | None
    created_at: datetime


class PublishCopyRequest(ApiModel):
    workspace_id: str
    asset_id: str | None = None
    brief: str = Field(default="", max_length=2000)
    profile_id: str | None = None


class PublishCopyResponse(ApiModel):
    title: str
    description: str
    tags: list[str]
