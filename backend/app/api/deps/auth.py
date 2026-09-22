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

#: 客户端自报身份的请求头,语法是 `<界面>/<版本>`(例如 `app/1.4.3`、`browser-extension/0.1.0`)。
CLIENT_VERSION_HEADER = "X-Mosael-Client"

#: 允许的界面。**这一栏会显示给管理员**,所以只认识我们自己发的那几个客户端 ——
#: 请求头是外部输入,不能让它变成一条能塞任意文本的通道。
CLIENT_SURFACES = ("app", "browser-extension")

#: `<界面>/<版本>`。版本部分只收像版本号的东西,同上。
_CLIENT_SHAPE = re.compile(
    r"^(?P<surface>" + "|".join(CLIENT_SURFACES) + r")/(?P<version>[0-9A-Za-z.+\-]{1,32})$"
)


def parse_client_header(value: str) -> tuple[str, str]:
    """`X-Mosael-Client` → (界面, 版本)。认不出来就是一对空串。

    **这个头此前是两个意思。** 前端发的是 `__APP_VERSION__`(`1.4.2`),而浏览器扩展发的是
    字面量 `browser-extension` —— 同一栏,一个是版本,一个是产品名。后端把它原样存进
    `auth_sessions.client_version`,管理页再照着渲染 `v{...}`:扩展用户那一行显示的是
    **「vbrowser-extension」**。两边各自都"对",错在没有人定义过这一栏是什么。

    认不出来就当没报(空)—— 老客户端在野外升不动,而"不知道"本来就是这一栏的合法状态,
    比编一个假的诚实。这不是兼容分支:它是对外部输入的校验,没有第二条代码路径。
    """
    found = _CLIENT_SHAPE.match(value.strip())
    return (found.group("surface"), found.group("version")) if found else ("", "")


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
    surface, version = parse_client_header(request.headers.get(CLIENT_VERSION_HEADER) or "")
    stamp = now()
    # 每个请求都写一次太吵(登录会话一天几千个请求)。只在自报的身份变了、或上次记录已经过了
    # 一分钟时才写 —— "最近在用"这件事不需要秒级精度。
    changed = version and (version != session.client_version or surface != session.client_surface)
    if changed:
        session.client_version = version
        session.client_surface = surface
    elif session.last_seen_at is not None and (stamp - session.last_seen_at).total_seconds() < 60:
        return
    session.last_seen_at = stamp
    db.commit()
