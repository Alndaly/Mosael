"""HTTP 认证插头:把一次请求认成一个人。

从 `app/core/permissions.py` 搬出来的 —— 这部分是纯 FastAPI(`Request` / `Query` / `Depends`),
调用方只有路由和组装根,住在 api 层才对。**授权**(能不能碰这个工作区)是另一回事,在
`app/domain/permissions.py`:它必须能被飞书回调这类非 HTTP 入口调用。
"""

from __future__ import annotations

import re

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.security import find_session, renew_if_stale
from app.db.models import AuthSession, User, now

#: 客户端自报版本的请求头。前端在 api/client 里统一带上(见 __APP_VERSION__)。
CLIENT_VERSION_HEADER = "X-Open-Studio-Client"

#: 版本号里能出现的字符。请求头是**外部输入** —— 只收像版本号的东西,别让这一栏变成一条
#: 能塞任意文本的通道(它会被原样显示在管理员的表格里)。
_VERSION_SHAPE = re.compile(r"^[0-9A-Za-z.+\-]{1,32}$")


def presented_token(
    request: Request,
    token: str | None = Query(default=None, include_in_schema=False),
) -> str:
    """这次请求带进来的凭据本身(Bearer 头,或 ?token= 那条给 <video>/<img> 用的旁路)。

    只做提取,不做校验 —— 校验是 get_current_user 的事,两者读的是同一处,所以不会出现
    「按一个来源认人、按另一个来源取值」。给需要**把调用方凭据继续往下传**的路由用:
    工具通道要让工具体回连本 API,它需要的正是调用方这一份,而不是另铸一份没人回收的新令牌。
    """
    header = request.headers.get("authorization", "")
    bearer = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else None
    return bearer or token or ""


def get_current_user(
    request: Request,
    db: Session = Depends(session_scope),
    token: str | None = Query(default=None, include_in_schema=False),
) -> User:
    candidate = presented_token(request, token)
    if not candidate:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = find_session(db, candidate)
    if session is not None and session.expires_at <= now():
        # 撞见就顺手删掉:过期的行不该在库里等着某次清理。铸造时的批量清理管的是"没人再碰的
        # 那些",这一条管的是"正好被碰到的那一条"——两者合起来,表不会因为无人重启而涨。
        db.delete(session)
        db.commit()
        session = None
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    renew_if_stale(db, session)
    _record_client(db, session, request)
    return user


def _record_client(db: Session, session: AuthSession, request: Request) -> None:
    """记下"这个人现在跑的是哪一版、最近一次是什么时候"。

    放在这里是因为它是**唯一**的登录身份收口点:每一个带凭据的请求都经过它,所以不需要在
    任何路由上再挂一次,也就不会有"这条路由忘了记"。
    """
    reported = (request.headers.get(CLIENT_VERSION_HEADER) or "").strip()
    version = reported if _VERSION_SHAPE.match(reported) else ""
    stamp = now()
    # 每个请求都写一次太吵(登录会话一天几千个请求)。只在版本变了、或上次记录已经过了一分钟
    # 时才写 —— "最近在用"这件事不需要秒级精度。
    if version and version != session.client_version:
        session.client_version = version
    elif session.last_seen_at is not None and (stamp - session.last_seen_at).total_seconds() < 60:
        return
    session.last_seen_at = stamp
    db.commit()
