from __future__ import annotations

import contextvars

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.roles import effective_perms, has_perm, role_at_least
from app.core.security import renew_if_stale
from app.core.usage_scope import bind_workspace
from app.db.models import Asset, AuthSession, Sequence, User, WorkspaceMember, WorkspaceMemberPerm, now

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
    return user


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
_request_method: contextvars.ContextVar[str] = contextvars.ContextVar("open_studio_request_method", default="GET")
_MUTATING = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def bind_request_method(method: str) -> None:
    _request_method.set((method or "GET").upper())


def ensure_workspace_member(db: Session, user: User, workspace_id: str) -> None:
    """Pure membership gate, method-agnostic — for read-only POSTs (search / retrieval
    test) that must stay open to viewers."""
    _membership(db, user, workspace_id)
    bind_workspace(workspace_id)


def ensure_workspace_access(db: Session, user: User, workspace_id: str) -> None:
    """The universal scoped-route chokepoint (also reached via require_asset /
    require_sequence_access). Any member may read; a mutating request additionally
    requires the `edit` perm, so viewers — and members with `edit` revoked — are
    read-only everywhere without per-route wiring. Routes needing a different perm
    (credentials, ai, delete, …) call ensure_workspace_perm explicitly instead."""
    member = _membership(db, user, workspace_id)
    if _request_method.get() in _MUTATING:
        overrides = {} if member.role == "owner" else member_overrides(db, workspace_id, user.id)
        if not has_perm(member.role, overrides, "edit"):
            raise HTTPException(status_code=403, detail="Permission denied: edit")
    # 通过闸门 = 这次请求确实是关于这个工作区的。用量记账据此归属,不必再让每个调用点
    # 把 workspace_id 一路穿到底(见 core/usage_scope 的说明)。放在校验之后:没过闸门的
    # 请求不该在上下文里留下痕迹。
    bind_workspace(workspace_id)


def member_overrides(db: Session, workspace_id: str, user_id: str) -> dict[str, bool]:
    rows = db.scalars(
        select(WorkspaceMemberPerm).where(
            WorkspaceMemberPerm.workspace_id == workspace_id,
            WorkspaceMemberPerm.user_id == user_id,
        )
    )
    return {row.perm: row.allowed for row in rows}


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


def ensure_workspace_perm(db: Session, user: User, workspace_id: str, perm: str) -> None:
    """Member must have `perm` — role default, adjusted by any per-member override.
    This is the write gate: mutating routes call it instead of ensure_workspace_access."""
    member = _membership(db, user, workspace_id)
    overrides = {} if member.role == "owner" else member_overrides(db, workspace_id, user.id)
    if not has_perm(member.role, overrides, perm):
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


def effective_member_perms(db: Session, workspace_id: str, user_id: str, role: str) -> dict[str, bool]:
    return effective_perms(role, member_overrides(db, workspace_id, user_id))


def require_asset(db: Session, user: User, asset_id: str) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise HTTPException(status_code=404, detail="Not found")
    ensure_workspace_access(db, user, asset.workspace_id)
    return asset


def require_sequence_access(db: Session, user: User, sequence_id: str) -> Sequence:
    sequence = db.get(Sequence, sequence_id)
    if sequence is None:
        raise HTTPException(status_code=404, detail="Not found")
    ensure_workspace_access(db, user, sequence.workspace_id)
    return sequence


def ensure_graph_node_privileges(db: Session, user: User, graph: object) -> None:
    """Gate the workflow nodes that grant host access rather than content access.

    A `code` node runs arbitrary Python on whatever machine hosts the backend. That is process
    isolated (subprocess, `-I`, PATH-only env, 20s, output cap) but deliberately *not* sandboxed:
    the code can read the filesystem and make outbound requests. On a single-user install the
    author is the machine owner, so this is a non-event. On a team/remote backend it is not —
    `edit` is the gate on every mutating workflow route, and editors hold `edit` by default, so
    without this check "can edit content" silently implies "can own the server".

    Same reasoning that already put provider credentials and the interpreter path behind
    `ensure_deployment_admin` (see its docstring); this closes the remaining path to the same
    capability. Checked when the graph is *persisted*, not when it runs: scheduler and webhook
    triggers have no acting user to check, and a graph that could never store a `code` node does
    not need a run-time gate. A single-user install owns its default workspace and is unaffected.
    """
    from app.core.config import settings
    from app.domain.workflows import NODE_TYPES, privileged_nodes_in_graph

    used = privileged_nodes_in_graph(graph)
    if not used:
        return
    # 部署级开关先于任何角色判断:这项能力**在这个部署里存不存在**,和「谁有资格用它」是两个问题。
    # 默认关 —— 见 core/config.server_side_code_execution 的说明,以及 ADR 0008 D2:
    # 真正的解法是隔离执行器,这个开关是它到位之前的止血。
    if not settings.server_side_code_execution:
        labels = "、".join(sorted(str(NODE_TYPES.get(t, {}).get("label") or t) for t in used))
        raise HTTPException(
            status_code=403,
            detail=f"这个部署关闭了服务端代码执行,无法保存含「{labels}」的内容",
        )
    try:
        ensure_deployment_admin(db, user)
    except HTTPException as exc:
        # ensure_deployment_admin 的通用文案是「Instance settings require admin with 'credentials'」,
        # 对着一张工作流画布看到这句没人懂自己撞了什么。换成点名节点的说法。
        labels = "、".join(sorted(str(NODE_TYPES.get(t, {}).get("label") or t) for t in used))
        raise HTTPException(
            status_code=exc.status_code,
            detail=f"「{labels}」节点会在后端主机上执行任意代码,只有管理员能保存含此类节点的工作流",
        ) from exc
