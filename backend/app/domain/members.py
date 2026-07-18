"""Workspace membership operations with the "last owner" invariant.

A workspace must always keep at least one owner — you can't demote or remove the last
one, or the workspace becomes unmanageable. That check-then-write must be atomic, so the
mutating ops run under a module lock (mirrors mibu-video's core/workspaces.py RLock).
Actor-level authorization (who may call these) is enforced in the route layer.
"""
from __future__ import annotations

import threading

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.roles import PERMS
from app.core.security import hash_password
from app.db.models import User, WorkspaceMember, WorkspaceMemberPerm

_lock = threading.RLock()


class MemberError(Exception):
    """Domain error → mapped to HTTP 400/409 by the route."""


def owners_count(db: Session, workspace_id: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner")
        )
        or 0
    )


def list_members(db: Session, workspace_id: str) -> list[tuple[User, WorkspaceMember]]:
    rows = db.execute(
        select(User, WorkspaceMember)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.created_at.asc())
    ).all()
    return [(user, member) for user, member in rows]


def add_member(db: Session, workspace_id: str, username: str, password: str, role: str) -> tuple[User, WorkspaceMember]:
    """Add a teammate. Creates the account when it doesn't exist yet (admin-builds-accounts
    onboarding); adds an existing account otherwise. Raises if already a member."""
    username = username.strip().lower()
    with _lock:
        user = db.scalar(select(User).where(User.username == username))
        if user is None:
            if not password or len(password) < 4:
                raise MemberError("New accounts need a password of at least 4 characters")
            user = User(username=username, password_hash=hash_password(password))
            db.add(user)
            db.flush()
        existing = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user.id})
        if existing is not None:
            raise MemberError("Already a member of this workspace")
        member = WorkspaceMember(workspace_id=workspace_id, user_id=user.id, role=role)
        db.add(member)
        db.commit()
        db.refresh(member)
    return user, member


def set_role(db: Session, workspace_id: str, user_id: str, role: str) -> WorkspaceMember:
    with _lock:
        member = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id})
        if member is None:
            raise MemberError("Not a member")
        if member.role == "owner" and role != "owner" and owners_count(db, workspace_id) <= 1:
            raise MemberError("Cannot demote the last owner")
        member.role = role
        if role == "owner":
            _clear_overrides(db, workspace_id, user_id)  # owner ignores overrides; drop stale rows
        db.commit()
        db.refresh(member)
    return member


def remove_member(db: Session, workspace_id: str, user_id: str) -> None:
    with _lock:
        member = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id})
        if member is None:
            raise MemberError("Not a member")
        if member.role == "owner" and owners_count(db, workspace_id) <= 1:
            raise MemberError("Cannot remove the last owner")
        _clear_overrides(db, workspace_id, user_id)
        db.delete(member)
        db.commit()


def set_perms(db: Session, workspace_id: str, user_id: str, overrides: dict[str, bool]) -> None:
    """Replace this member's per-perm overrides with `overrides` (only keys that differ
    from the role default need to be stored, but we accept any and prune no-ops)."""
    member = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id})
    if member is None:
        raise MemberError("Not a member")
    if member.role == "owner":
        raise MemberError("Owner always has every permission")
    _clear_overrides(db, workspace_id, user_id)
    for perm, allowed in overrides.items():
        if perm in PERMS:
            db.add(WorkspaceMemberPerm(workspace_id=workspace_id, user_id=user_id, perm=perm, allowed=bool(allowed)))
    db.commit()


def _clear_overrides(db: Session, workspace_id: str, user_id: str) -> None:
    for row in db.scalars(
        select(WorkspaceMemberPerm).where(
            WorkspaceMemberPerm.workspace_id == workspace_id,
            WorkspaceMemberPerm.user_id == user_id,
        )
    ):
        db.delete(row)
