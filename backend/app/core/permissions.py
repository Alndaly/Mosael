from __future__ import annotations

from fastapi import Depends, HTTPException, Query, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import session_scope
from app.db.models import Asset, AuthSession, Sequence, User, WorkspaceMember

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


def ensure_workspace_access(db: Session, user: User, workspace_id: str) -> None:
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user.id,
        )
    )
    if member is None:
        raise HTTPException(status_code=404, detail="Not found")


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
