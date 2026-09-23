"""项目的请求/响应体。"""

from __future__ import annotations

from datetime import datetime
from pydantic import Field
from app.api.schemas.base import ApiModel, OrmModel

class ProjectCreate(ApiModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=180)


class ProjectOut(OrmModel):
    id: str
    workspace_id: str
    name: str
    active_sequence_id: str | None


class ProjectWithStatsOut(ProjectOut):
    """列表页项目卡片用的汇总信息;单个项目端点仍返回精简 ProjectOut。"""

    asset_count: int = 0
    sequence_count: int = 0
    timeline_duration: float = 0.0
    #: 卡片封面:时间线上最早出现的画面,没有时是项目自己的第一张图 / 第一段视频。
    cover_asset_id: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
