from __future__ import annotations

import contextvars

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.core.roles import effective_perms, has_perm, role_at_least
from app.db.models import Asset, AuthSession, Sequence, User, WorkspaceMember, WorkspaceMemberPerm

"""
Single permission entry point (plan §9.3).

- Authentication: opaque bearer token (Authorization header) resolved to a
  local user. Media endpoints may pass ?token= because <video>/<img> cannot
  set headers.
- Workspace scoping: unknown or foreign resources return 404, never 403,
  to avoid leaking existence.
"""


def get_current_user(
    request: Request,
    db: Session = Depends(session_scope),
    token: str | None = Query(default=None, include_in_schema=False),
) -> User:
    header = request.headers.get("authorization", "")
    bearer = header.removeprefix("Bearer ").strip() if header.startswith("Bearer ") else None
    candidate = bearer or token
    if not candidate:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session = db.get(AuthSession, candidate)
    if session is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    user = db.get(User, session.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
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


def ensure_instance_admin(db: Session, user: User, perm: str = "credentials") -> None:
    """Gate for configuration that belongs to the INSTANCE, not to a workspace.

    Provider profiles and their keys, the TTS interpreter path, and plugin enablement are
    shared by every workspace, so there is no workspace id to scope them by — which is why
    these routes had no gate at all and "logged in" was the only bar. That is far too weak
    for settings that reach the local filesystem and make outbound requests carrying stored
    credentials: any viewer, in any workspace, could repoint a provider at a host they own
    or set the interpreter path that later gets executed.

    Require the caller to be owner/admin somewhere AND to hold `perm` there. A single-user
    install is unaffected — that user owns their default workspace.
    """
    memberships = list(db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)))
    for member in memberships:
        if not role_at_least(member.role, "admin"):
            continue
        overrides = {} if member.role == "owner" else member_overrides(db, member.workspace_id, user.id)
        if has_perm(member.role, overrides, perm):
            return
    raise HTTPException(status_code=403, detail=f"Instance settings require admin with '{perm}'")


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
    `ensure_instance_admin` (see its docstring); this closes the remaining path to the same
    capability. Checked when the graph is *persisted*, not when it runs: scheduler and webhook
    triggers have no acting user to check, and a graph that could never store a `code` node does
    not need a run-time gate. A single-user install owns its default workspace and is unaffected.
    """
    from app.domain.workflows import NODE_TYPES, privileged_nodes_in_graph

    used = privileged_nodes_in_graph(graph)
    if not used:
        return
    try:
        ensure_instance_admin(db, user, "credentials")
    except HTTPException as exc:
        # ensure_instance_admin 的通用文案是「Instance settings require admin with 'credentials'」,
        # 对着一张工作流画布看到这句没人懂自己撞了什么。换成点名节点的说法。
        labels = "、".join(sorted(str(NODE_TYPES.get(t, {}).get("label") or t) for t in used))
        raise HTTPException(
            status_code=exc.status_code,
            detail=f"「{labels}」节点会在后端主机上执行任意代码,只有管理员能保存含此类节点的工作流",
        ) from exc
