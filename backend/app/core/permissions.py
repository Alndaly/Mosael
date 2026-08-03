from __future__ import annotations

import contextvars
import re

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.roles import role_at_least
from app.core.security import renew_if_stale
from app.core.usage_scope import bind_workspace
from app.db.models import Asset, AuthSession, Sequence, User, WorkspaceMember, now

"""
Single permission entry point (plan §9.3).

- Authentication: opaque bearer token (Authorization header) resolved to a
  local user. Media endpoints may pass ?token= because <video>/<img> cannot
  set headers.
- Workspace scoping: unknown or foreign resources return 404, never 403,
  to avoid leaking existence.
"""


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


#: 客户端自报版本的请求头。前端在 api/client 里统一带上(见 __APP_VERSION__)。
CLIENT_VERSION_HEADER = "X-Open-Studio-Client"


def get_current_user(
    request: Request,
    db: Session = Depends(session_scope),
    token: str | None = Query(default=None, include_in_schema=False),
) -> User:
    candidate = presented_token(request, token)
    if not candidate:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = db.get(AuthSession, candidate)
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


#: 版本号里能出现的字符。请求头是**外部输入** —— 只收像版本号的东西,别让这一栏变成一条
#: 能塞任意文本的通道(它会被原样显示在管理员的表格里)。
_VERSION_SHAPE = re.compile(r"^[0-9A-Za-z.+\-]{1,32}$")


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


def _membership(db: Session, user: User, workspace_id: str) -> WorkspaceMember:
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if member is None:
        # Non-members get 404, never 403 — don't leak that the workspace exists.
        raise HTTPException(status_code=404, detail="Not found")
    return member


# The current request's HTTP method, bound by the ASGI middleware in app/main.py.
# Lets the shared access chokepoint stay read-open but write-gated without every route
# passing the method through. Defaults to GET so non-HTTP call paths (tests, workers,
# daemon jobs) are treated as reads and never spuriously 403.


def ensure_workspace_member(db: Session, user: User, workspace_id: str) -> None:
    """Pure membership gate, method-agnostic — for read-only POSTs (search / retrieval
    test) that must stay open to viewers."""
    _membership(db, user, workspace_id)
    bind_workspace(workspace_id)


def ensure_workspace_access(db: Session, user: User, workspace_id: str) -> None:
    """**只读闸**:他是不是这个工作区的人。任何成员都能过。

    此前它还兼职判写权限 —— 「当前请求是不是 POST?是就额外要 edit」。那个方法名读自一个只在
    ASGI 中间件里绑定的 ContextVar,**默认 GET**,于是这道闸的正确性不取决于路由写了什么,而
    取决于它碰巧是从哪儿被调用的:后台线程(定时器、自动放行、工作流引擎、飞书回调)里同一个
    函数会安静地放行 viewer(ADR 0008 §2.2 与 D5,tests/test_write_permission_is_explicit.py
    里有复现)。

    现在要写的路由自己点名 `ensure_workspace_perm(..., "edit")`。少一个"聪明"的推断。
    """
    _membership(db, user, workspace_id)
    # 通过闸门 = 这次请求确实是关于这个工作区的。用量记账据此归属,不必再让每个调用点
    # 把 workspace_id 一路穿到底(见 core/usage_scope 的说明)。放在校验之后:没过闸门的
    # 请求不该在上下文里留下痕迹。
    bind_workspace(workspace_id)




def workspace_role(db: Session, user: User, workspace_id: str) -> str | None:
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    return member.role if member else None


def ensure_workspace_role(db: Session, user: User, workspace_id: str, minimum: str) -> str:
    """Member must hold at least `minimum` role. Returns the caller's role."""
    member = _membership(db, user, workspace_id)
    if not role_at_least(member.role, minimum):
        raise HTTPException(status_code=403, detail="Insufficient workspace role")
    return member.role


#: 老权限位 → 最低角色。**这不是一层新的间接**,是给 47 处调用点一次性换名的对照表:
#: 位与位之间的区别在这个产品里从来没有真实场景,而角色阶梯有。
_PERM_ROLE = {
    "upload": "editor",
    "edit": "editor",
    "delete": "editor",
    "export": "editor",
    "ai": "editor",
    "schedule": "editor",
    "publish": "editor",
    "members": "admin",
}


def ensure_workspace_perm(db: Session, user: User, workspace_id: str, perm: str) -> None:
    """写闸:成员的角色要够。

    保留 `perm` 这个参数是为了让调用点自己说清「这是哪一类操作」—— 它读起来比一个裸的 "editor"
    有信息(`ensure_workspace_perm(..., "publish")` 一眼看出这条路由在发东西)。但它**不再是一个
    可以逐位开关的能力**,只是映射到一档角色(见 _PERM_ROLE)。
    """
    minimum = _PERM_ROLE.get(perm, "admin")
    member = _membership(db, user, workspace_id)
    if not role_at_least(member.role, minimum):
        raise HTTPException(status_code=403, detail=f"Permission denied: {perm}")
    bind_workspace(workspace_id)


def ensure_deployment_admin(db: Session, user: User) -> None:
    """守**这个后端实例**的配置:网络出口、插件启用、解释器路径、模型下载。

    判据是 `users.is_deployment_admin` 一列 —— 一个事实,不是一个推断。

    此前它叫 `ensure_deployment_admin`,判据是「在**任意**工作区里是 owner/admin 且在那里持有某个
    权限位」。而任何登录用户都能新建工作区并在里面是 owner,所以那个判据是**自助的**:

        viewer 改实例级网络设置                  403
        他自己新建一个工作区之后再改一次          200   ← 复现过

    顺带,它的第二个条件从来没起过作用:editor 默认持有除 `members` 外的全部权限位,于是
    「持有 perm」恒真 —— 真正的判据只剩「角色 ≥ admin」。所以新判据不再接受 perm 参数。

    单机安装不受影响:那个人就是引导账号,库里第一个用户自动持有这一列。
    """
    if not user.is_deployment_admin:
        raise HTTPException(status_code=403, detail="这项设置属于整个部署,只有部署管理员能改")




def require_asset(db: Session, user: User, asset_id: str, *, perm: str | None = None) -> Asset:
    """取素材并过闸。`perm` 是**写**路由必须点名的那一项(见 ensure_workspace_perm);
    只读路由不传,拿到的就是只读闸。"""
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Not found")
    if perm is None:
        ensure_workspace_access(db, user, asset.workspace_id)
    else:
        ensure_workspace_perm(db, user, asset.workspace_id, perm)
    return asset


def require_sequence_access(db: Session, user: User, sequence_id: str, *, perm: str | None = None) -> Sequence:
    """取序列并过闸。写路由传 `perm="edit"` —— 权限写在调用点上,而不是从请求方法推。"""
    sequence = db.get(Sequence, sequence_id)
    if sequence is None:
        raise HTTPException(status_code=404, detail="Not found")
    if perm is None:
        ensure_workspace_access(db, user, sequence.workspace_id)
    else:
        ensure_workspace_perm(db, user, sequence.workspace_id, perm)
    return sequence
