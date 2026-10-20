"""本地保存 MosaelCloud 绑定的请求/响应体(见 domain/cloud_binding)。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from app.api.schemas.base import ApiModel


class CloudBindingStartIn(ApiModel):
    device_name: str = Field(default="", max_length=120)


class CloudBindingStartOut(ApiModel):
    status: Literal["pending_authorization"] = "pending_authorization"
    #: 短期轮询码,不是账号凭据:只有等用户在官网确认之后,它才能换到那一份凭据。
    #: 交给渲染层是为了让它能回来调 complete;真正的 token 从不经过这里(见 domain/cloud_binding)。
    device_code: str
    user_code: str
    verification_uri: str
    verification_uri_complete: str
    expires_in: int
    interval: int


class CloudBindingCompleteIn(ApiModel):
    device_code: str = Field(min_length=1, max_length=512)


class CloudBindingCompleteOut(ApiModel):
    status: Literal["pending", "approved"]
    email: str | None = None
    device_id: str | None = None


class CloudBindingOut(ApiModel):
    #: 这个部署接没接 MosaelCloud(`MOSAEL_CLOUD_URL`)。没接时界面把入口置灰,不靠"点一次才知道"。
    configured: bool
    bound: bool
    email: str | None = None
    device_id: str | None = None
    created_at: datetime | None = None


class CloudBindingRemovedOut(ApiModel):
    removed: bool
