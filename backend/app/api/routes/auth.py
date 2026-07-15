from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import AuthCredentials, AuthOut, UserOut
from app.core.security import hash_password, new_session_token, verify_password
from app.db.models import AuthSession, User, Workspace, WorkspaceMember

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=AuthOut)
def register(body: AuthCredentials, db: DbSession) -> AuthOut:
    existing = db.scalar(select(User).where(User.username == body.username))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already exists")
    user = User(username=body.username, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    _adopt_orphan_workspaces(db, user)
    token = _create_session(db, user)
    db.commit()
    return AuthOut(token=token, user=UserOut.model_validate(user))


@router.post("/auth/login", response_model=AuthOut)
def login(body: AuthCredentials, db: DbSession) -> AuthOut:
    user = db.scalar(select(User).where(User.username == body.username))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = _create_session(db, user)
    db.commit()
    return AuthOut(token=token, user=UserOut.model_validate(user))


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.post("/auth/logout")
def logout(request: Request, db: DbSession, user: CurrentUser) -> dict:
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip()
    session = db.get(AuthSession, token)
    if session is not None and session.user_id == user.id:
        db.delete(session)
        db.commit()
    return {"ok": True}


@router.get("/auth/bootstrap")
def bootstrap(db: DbSession) -> dict:
    """Whether any local account exists — decides register vs login screen."""
    count = db.scalar(select(func.count()).select_from(User)) or 0
    return {"has_users": count > 0}


def _create_session(db: DbSession, user: User) -> str:
    token = new_session_token()
    db.add(AuthSession(token=token, user_id=user.id))
    return token


def _adopt_orphan_workspaces(db: DbSession, user: User) -> None:
    """Local upgrade path: the first account inherits pre-auth workspaces."""
    members_exist = db.scalar(select(WorkspaceMember).limit(1))
    if members_exist is not None:
        return
    for workspace in db.scalars(select(Workspace)):
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
