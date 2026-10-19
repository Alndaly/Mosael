"""HTTP 依赖:一次请求一个会话、cookie 认人、Bearer 认设备。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from cloud.config import CloudConfig
from cloud.errors import CloudError
from cloud.models import CloudDevice, CloudSession, CloudUser, now
from cloud.security import token_digest


def get_db(request: Request) -> Iterator[Session]:
    session = request.app.state.db.session()
    try:
        yield session
    finally:
        session.close()


DbSession = Annotated[Session, Depends(get_db)]


def get_config(request: Request) -> CloudConfig:
    return request.app.state.config


CurrentConfig = Annotated[CloudConfig, Depends(get_config)]


def current_user(request: Request, db: DbSession, config: CurrentConfig) -> CloudUser:
    raw = request.cookies.get(config.cookie_name, "")
    if not raw:
        raise CloudError(401, "not_authenticated")
    session = db.get(CloudSession, token_digest(raw))
    if session is None:
        raise CloudError(401, "not_authenticated")
    if session.expires_at <= now():
        # 撞见就顺手删掉:过期的行不该在库里等着某次清理。
        db.delete(session)
        db.commit()
        raise CloudError(401, "not_authenticated")
    user = db.get(CloudUser, session.user_id)
    if user is None:
        raise CloudError(401, "not_authenticated")
    return user


CurrentUser = Annotated[CloudUser, Depends(current_user)]


def current_device(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> tuple[CloudDevice, CloudUser]:
    """桌面端拿绑定到的云端凭据认自己。没有 cookie、没有 CSRF —— 它本来就不是浏览器会话。"""
    scheme, _, raw = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not raw.strip():
        raise CloudError(401, "invalid_device_token")
    device = db.query(CloudDevice).filter(CloudDevice.token_hash == token_digest(raw.strip())).one_or_none()
    if device is None:
        raise CloudError(401, "invalid_device_token")
    user = db.get(CloudUser, device.user_id)
    if user is None:
        raise CloudError(401, "invalid_device_token")
    return device, user


CurrentDevice = Annotated[tuple[CloudDevice, CloudUser], Depends(current_device)]
