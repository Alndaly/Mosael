from __future__ import annotations

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


def ensure_workspace_access(db: Session, user: User, workspace_id: str) -> None:
    """Membership gate (any role) — used by read paths and as the base for the
    role/perm gates below."""
    _membership(db, user, workspace_id)


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
