from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.api.schemas.base import ApiModel, OrmModel


class CommunityDeviceOut(ApiModel):
    """一次正在等的设备授权:界面显示 `user_code`,用系统浏览器打开 `verification_uri`。"""

    user_code: str
    verification_uri: str
    #: 还剩几秒作废。
    expires_in: int


class CommunityStatusOut(ApiModel):
    """设置页「社区账号」那一节:配没配社区、连没连、连的是谁,以及正在等的那次授权。"""

    configured: bool
    #: 社区站点根(「我的提交」「我的分享」这些网页链接从它拼)。
    origin: str
    connected: bool
    handle: str
    display_name: str
    pending: CommunityDeviceOut | None = None


class CommunityPollOut(ApiModel):
    """轮询一次设备授权。`pending` 还在等;`connected` 连上了;`expired` / `denied` 这一次作废,要重来。"""

    state: Literal["idle", "pending", "connected", "expired", "denied"]
    status: CommunityStatusOut


class CommunityUrlIn(ApiModel):
    url: str = Field(default="", max_length=500)


class CommunityUrlOut(ApiModel):
    url: str
    default_url: str


class BoardShareIn(ApiModel):
    workspace_id: str
    title: str = Field(default="", max_length=180)
    visibility: Literal["unlisted", "public"] = "unlisted"


class BoardShareUpdate(ApiModel):
    workspace_id: str
    title: str | None = Field(default=None, max_length=180)
    visibility: Literal["unlisted", "public"] | None = None


class BoardShareOut(OrmModel):
    """这张画板分享出去的那条链接(本机记着的)。"""

    slug: str
    url: str
    version: int
    title: str
    visibility: str
    updated_at: datetime


class BoardShareStateOut(ApiModel):
    """分享面板一打开要的:这张板分享过没有,以及这个人能不能分享(连没连社区)。"""

    share: BoardShareOut | None = None
    status: CommunityStatusOut


class WorkflowPublishIn(ApiModel):
    title: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=8)
    #: 封面:素材库里一张图的 id。不填 = 没有封面。
    cover_asset_id: str | None = None


class PluginPublishIn(ApiModel):
    summary: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=8)


class CommunityPublishOut(ApiModel):
    """发布到社区的结果。`status`:工作流是 `published`(发布即上架),插件是 `pending`(审核中)。"""

    slug: str
    url: str
    version: str
    status: str


# --- 资产(ADR 0027 §4) -------------------------------------------------------


class EntityPublishIn(ApiModel):
    workspace_id: str
    #: 真人人物:这一次确认「已获得本人同意公开」。虚构的不看它。
    consent_confirmed: bool = False
    title: str = Field(default="", max_length=120)
    summary: str = Field(default="", max_length=300)
    #: 不给 = 用资产自己的标签。
    tags: list[str] | None = Field(default=None, max_length=8)


class EntityCommunityPublishedOut(ApiModel):
    """这个资产发到社区的那一条。`status`:虚构的 `approved`(发布即上架),真人的 `pending`(审核中)。"""

    slug: str
    url: str
    version: str
    status: str
    origin: str


class EntityCommunitySourceOut(ApiModel):
    """这个资产是从社区的哪一条导入的。"""

    slug: str
    version: str
    origin: str
    url: str


class EntityCommunityOut(ApiModel):
    """资产详情里「社区」那一格。`latest_version`:导入的那一条在社区上现在是第几版(连不上时为空)。"""

    published: EntityCommunityPublishedOut | None = None
    source: EntityCommunitySourceOut | None = None
    latest_version: str | None = None
    status: CommunityStatusOut


class EntityImportIn(ApiModel):
    workspace_id: str
    #: 社区资产页的地址(`…/assets/<slug>`),或 slug 本身。
    link: str = Field(min_length=1, max_length=500)


class CommunityAssetOut(ApiModel):
    """「从社区导入」弹窗里的一行。"""

    slug: str
    title: str
    summary: str = ""
    asset_kind: str
    real_person: bool = False
    cover_url: str | None = None
    reference_count: int = 0
    variant_count: int = 0
    downloads: int = 0
    version: str | None = None
    author_name: str = ""


class CommunityAssetPageOut(ApiModel):
    items: list[CommunityAssetOut]
    next_cursor: str | None = None
