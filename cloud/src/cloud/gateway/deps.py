"""网关的认人:`Authorization: Bearer mct_…` → 设备令牌 → 用户。

**不看 cookie**:网关的调用方是桌面后端,不是浏览器;浏览器会话在这里一律不算登录。
账号接口(`api/deps.current_user`)两条路都认,网关只认这一条。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request

from cloud.api.deps import DbSession, bearer_token
from cloud.domain import device_tokens
from cloud.errors import CloudError
from cloud.models import CloudDeviceToken, CloudUser


@dataclass(frozen=True)
class Device:
    token: CloudDeviceToken
    user: CloudUser


def current_device(request: Request, db: DbSession) -> Device:
    token = device_tokens.authenticate(db, bearer_token(request))
    if token is None:
        raise CloudError(401, "device_token_invalid")
    user = db.get(CloudUser, token.user_id)
    if user is None:
        raise CloudError(401, "device_token_invalid")
    return Device(token=token, user=user)


CurrentDevice = Annotated[Device, Depends(current_device)]
