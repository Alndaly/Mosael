"""HTTP 依赖:一次请求一个数据库会话;认人认浏览器的会话 cookie 或桌面端的设备令牌。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from cloud.config import CloudConfig
from cloud.domain import device_tokens
from cloud.errors import CloudError
from cloud.domain import admin as admin_domain
from cloud.models import CloudSession, CloudUser, now
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


def bearer_token(request: Request) -> str:
    """`Authorization: Bearer <令牌>` 里的令牌;没有或不是 Bearer 就是空串。"""
    scheme, _, value = request.headers.get("authorization", "").partition(" ")
    return value.strip() if scheme.lower() == "bearer" else ""


def _device_user(db: Session, raw: str) -> CloudUser | None:
    token = device_tokens.authenticate(db, raw)
    return db.get(CloudUser, token.user_id) if token is not None else None


def browser_user(request: Request, db: DbSession, config: CurrentConfig) -> CloudUser:
    """只认浏览器会话 cookie,不认桌面设备令牌。"""
    raw = request.cookies.get(config.cookie_name, "")
    if not raw:
        raise CloudError(401, "not_authenticated")
    session = db.get(CloudSession, token_digest(raw))
    if session is None:
        raise CloudError(401, "not_authenticated")
    if session.expires_at <= now():
        db.delete(session)
        db.commit()
        raise CloudError(401, "not_authenticated")
    user = db.get(CloudUser, session.user_id)
    if user is None:
        raise CloudError(401, "not_authenticated")
    return user


def current_user(request: Request, db: DbSession, config: CurrentConfig) -> CloudUser:
    """认人有两条路,**一个请求只走一条**:

    - 带了 `Authorization: Bearer` → 桌面端,只认设备令牌(ADR 0088);认不出就是 `device_token_invalid`,
      不再回头看 cookie —— 桌面端据此清掉本地登录,而不是被一枚碰巧还在的 cookie 混过去;
    - 否则 → 浏览器,只认会话 cookie。

    Bearer 不受 CSRF 影响(浏览器不会替跨站页面自动带上它),写请求的同源闸照旧对两条路都生效。
    """
    raw_bearer = bearer_token(request)
    if raw_bearer:
        user = _device_user(db, raw_bearer)
        if user is None:
            raise CloudError(401, "device_token_invalid")
        return user
    return browser_user(request, db, config)


CurrentUser = Annotated[CloudUser, Depends(current_user)]


def current_admin(request: Request, db: DbSession, config: CurrentConfig) -> CloudUser:
    """管理端身份:必须是浏览器会话 + `role=admin`。设备令牌一律拒绝。"""
    if bearer_token(request):
        raise CloudError(403, "admin_requires_browser")
    user = browser_user(request, db, config)
    if not admin_domain.is_admin(user):
        raise CloudError(403, "admin_required")
    return user


CurrentAdmin = Annotated[CloudUser, Depends(current_admin)]


def optional_user(request: Request, db: DbSession, config: CurrentConfig) -> CloudUser | None:
    """公开读接口用:带了有效凭据(设备令牌或会话)就认出是谁,没有(或失效)就当游客。

    **不报 401**:浏览不需要登录;`liked_by_me` / `favorited_by_me` 在游客这里是 false。
    """
    raw_bearer = bearer_token(request)
    if raw_bearer:
        return _device_user(db, raw_bearer)
    raw = request.cookies.get(config.cookie_name, "")
    if not raw:
        return None
    session = db.get(CloudSession, token_digest(raw))
    if session is None or session.expires_at <= now():
        return None
    return db.get(CloudUser, session.user_id)


MaybeUser = Annotated[CloudUser | None, Depends(optional_user)]
