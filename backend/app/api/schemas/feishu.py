"""飞书接入:机器人、绑定与一次性绑定码。"""

from __future__ import annotations

from datetime import datetime
from pydantic import Field
from app.api.schemas.base import ApiModel, OrmModel

class FeishuBotCreate(ApiModel):
    workspace_id: str
    name: str = Field(default="Mosael 助手", max_length=160)
    app_id: str = Field(min_length=1, max_length=120)
    app_secret: str = Field(min_length=1, max_length=200)
    capability: str = Field(default="editor", pattern="^(readonly|editor|full)$")


class FeishuBotUpdate(ApiModel):
    name: str | None = Field(default=None, max_length=160)
    capability: str | None = Field(default=None, pattern="^(readonly|editor|full)$")
    enabled: bool | None = None


class FeishuBotOut(OrmModel):
    id: str
    workspace_id: str
    name: str
    app_id: str
    capability: str
    enabled: bool
    status: str
    status_detail: str
    created_at: datetime


class FeishuOnboardingOut(ApiModel):
    phase: str
    qr_url: str | None = None
    user_code: str | None = None
    error: str | None = None
    app_id: str | None = None


class FeishuBindCodeOut(ApiModel):
    code: str
    expires_at: datetime


class FeishuBindingOut(ApiModel):
    open_id: str
    user_id: str
    username: str
