"""路由的依赖:数据库会话、当前用户、客户端 IP、审核员权限。"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from community.context import Context
from community.errors import ApiError
from community.models import ROLE_ADMIN, ROLE_MODERATOR, STATUS_ACTIVE, AuthSession, User
from community.tokens import decode_access


def get_ctx(request: Request) -> Context:
    return request.app.state.ctx


def get_db(request: Request) -> Iterator[Session]:
    session = get_ctx(request).sessions()
    try:
        yield session
    finally:
        session.close()


def client_ip(request: Request) -> str:
    """客户端 IP。反代后面由 uvicorn 的 --proxy-headers 按 X-Forwarded-For 还原(见 Dockerfile)。"""
    return (request.client.host if request.client else "") or ""


@dataclass(frozen=True)
class Principal:
    user: User
    session_id: str

    @property
    def is_moderator(self) -> bool:
        return self.user.role in (ROLE_MODERATOR, ROLE_ADMIN)


def _bearer(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def resolve_principal(request: Request, db: Session) -> Principal | None:
    token = _bearer(request)
    if token is None:
        return None
    claims = decode_access(get_ctx(request).keys, token)
    session = db.get(AuthSession, str(claims.get("sid")))
    # 访问令牌是无状态的,但会话吊销(退出、改密码、被盗检测)要立刻生效 —— 按 sid 查一次会话。
    if session is None or session.revoked_at is not None or session.user_id != claims.get("sub"):
        raise ApiError(401, "unauthorized")
    user = db.get(User, session.user_id)
    if user is None:
        raise ApiError(401, "unauthorized")
    if user.status != STATUS_ACTIVE:
        raise ApiError(403, "banned")
    return Principal(user=user, session_id=session.id)


def optional_principal(request: Request, db: Annotated[Session, Depends(get_db)]) -> Principal | None:
    return resolve_principal(request, db)


def require_principal(request: Request, db: Annotated[Session, Depends(get_db)]) -> Principal:
    principal = resolve_principal(request, db)
    if principal is None:
        raise ApiError(401, "unauthorized")
    return principal


def require_moderator(principal: Annotated[Principal, Depends(require_principal)]) -> Principal:
    if not principal.is_moderator:
        raise ApiError(403, "forbidden")
    return principal


Db = Annotated[Session, Depends(get_db)]
Ctx = Annotated[Context, Depends(get_ctx)]
CurrentUser = Annotated[Principal, Depends(require_principal)]
MaybeUser = Annotated[Principal | None, Depends(optional_principal)]
Moderator = Annotated[Principal, Depends(require_moderator)]

__all__ = [
    "Ctx",
    "CurrentUser",
    "Db",
    "MaybeUser",
    "Moderator",
    "Principal",
    "client_ip",
    "get_ctx",
    "get_db",
    "resolve_principal",
]
