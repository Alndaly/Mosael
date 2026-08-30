"""Browser automation API schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BrowserProfileOut(BaseModel):
    id: str
    workspace_id: str
    name: str
    partition: str
    proxy: str | None = None
    enabled: bool
    last_used_at: datetime | None = None
    created_at: datetime
    # 若被发布账号绑定,回其平台/账号 id + 登录态(浏览器池页据此标注「发布账号」并显示登录状态、
    # 复用登录/复检动作);通用档案这些为 None。
    platform: str | None = None
    bound_account_id: str | None = None
    binding_status: str | None = None
    last_checked_at: datetime | None = None
    last_error: str | None = None
    # 归属:是不是我的、有没有被放进当前工作区(见 domain/sharing)。只有主人能改共享状态。
    is_mine: bool = True
    shared: bool = False


class BrowserProfileCreate(BaseModel):
    workspace_id: str
    name: str = Field(min_length=1, max_length=160)
    proxy: str | None = None


class BrowserProfileUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=160)
    proxy: str | None = None
    enabled: bool | None = None
