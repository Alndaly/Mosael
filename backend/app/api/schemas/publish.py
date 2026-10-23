"""Publishing domain request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from app.api.schemas.base import ApiModel, OrmModel
from app.api.schemas.failures import FailureReadout


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
    #: 这个平台**能发**哪几种形状(ADR 0076):video / image-text / article。
    kinds: list[str] = Field(default_factory=lambda: ["video"])
    #: 我们**已经会发**的那几种(界面只列这些;`kinds - implemented_kinds` 是待做的进度)。
    implemented_kinds: list[str] = Field(default_factory=lambda: ["video"])
    #: 每种形状的上限(张数 / 正文字数),键是形状名;没核实的值不出现,不猜。
    content_limits: dict[str, dict] = Field(default_factory=dict)
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
    #: 这份任务的素材,按发出去的顺序。视频就是**只有一个元素**的那个列表 —— 没有第二种传法。
    asset_ids: list[str] = Field(min_length=1, max_length=64)
    #: 内容形状(ADR 0076):video / image-text / article。**必填**:没有"默认当视频"这一档,
    #: 不然同一个入口要同时想两种形状(形状决定素材怎么发、正文在哪一格)。
    content_kind: str = Field(max_length=20)
    #: 正文 / 长文(图文与文章用)。以前正文塞在 `options.description` 里,现在归位。
    body: str = Field(default="", max_length=40000)
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


class PublishTaskOut(FailureReadout, ApiModel):
    id: str
    workspace_id: str
    account_id: str
    account_name: str
    platform: str
    #: 素材已经删了的那条发布记录为空(记录留着,见 db.model_slices.publish.PublishTask.asset_id)。
    asset_id: str | None
    #: 这条发的是什么形状、几份素材(图文 / 文章多份;视频与老任务一份)。
    asset_ids: list[str] = Field(default_factory=list)
    content_kind: str = "video"
    body: str = ""
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
