"""HTTP 依赖:一次请求一个会话、cookie 认人。"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from cloud.config import CloudConfig
from cloud.errors import CloudError
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


def optional_user(request: Request, db: DbSession, config: CurrentConfig) -> CloudUser | None:
    """公开读接口用:带了有效会话就认出是谁,没有(或过期)就当游客。

    **不报 401**:浏览不需要登录;`liked_by_me` / `favorited_by_me` 在游客这里是 false。
    """
    raw = request.cookies.get(config.cookie_name, "")
    if not raw:
        return None
    session = db.get(CloudSession, token_digest(raw))
    if session is None or session.expires_at <= now():
        return None
    return db.get(CloudUser, session.user_id)


MaybeUser = Annotated[CloudUser | None, Depends(optional_user)]
