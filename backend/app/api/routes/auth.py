from __future__ import annotations

import time

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import AuthCredentials, AuthOut, PasswordUpdate, RegisterCredentials, UserOut, UserProfileUpdate
from app.core.config import settings
from app.core.security import hash_password, mint_login_session, verify_password
from app.db.models import AuthSession, User, Workspace, WorkspaceMember

router = APIRouter(tags=["auth"])


@router.post("/auth/register", response_model=AuthOut)
def register(body: RegisterCredentials, db: DbSession) -> AuthOut:
    username = _normalize_username(body.username)
    existing = db.scalar(select(User).where(User.username == username))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already exists")
    user = User(
        username=username,
        display_name=_clean_display_name(body.display_name, username),
        signature="",
        password_hash=hash_password(body.password),
    )
    db.add(user)
    db.flush()
    _adopt_orphan_workspaces(db, user)
    token = _create_session(db, user)
    db.commit()
    return AuthOut(token=token, user=UserOut.model_validate(user))


@router.post("/auth/login", response_model=AuthOut)
def login(body: AuthCredentials, db: DbSession) -> AuthOut:
    user = db.scalar(select(User).where(User.username == _normalize_username(body.username)))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = _create_session(db, user)
    db.commit()
    return AuthOut(token=token, user=UserOut.model_validate(user))


@router.get("/auth/me", response_model=UserOut)
def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.patch("/auth/me", response_model=UserOut)
def update_me(body: UserProfileUpdate, db: DbSession, user: CurrentUser) -> UserOut:
    username = _normalize_username(body.username)
    if username != user.username:
        existing = db.scalar(select(User).where(User.username == username, User.id != user.id))
        if existing is not None:
            raise HTTPException(status_code=409, detail="Username already exists")
    user.username = username
    user.display_name = _clean_display_name(body.display_name, username)
    user.signature = body.signature.strip()
    db.commit()
    db.refresh(user)
    return UserOut.model_validate(user)


_AVATAR_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_AVATAR_MAX_BYTES = 4 * 1024 * 1024


@router.post("/auth/me/avatar", response_model=UserOut)
async def upload_avatar(db: DbSession, user: CurrentUser, file: UploadFile = File(...)) -> UserOut:
    """上传/替换头像:落 data_dir/avatars/<uid>-<ts>.<ext>,key 带时间戳天然破缓存。"""
    ext = _AVATAR_TYPES.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(status_code=415, detail="仅支持 PNG / JPEG / WebP 图片")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="空文件")
    if len(data) > _AVATAR_MAX_BYTES:
        raise HTTPException(status_code=413, detail="头像不能超过 4MB")
    avatars_dir = settings.data_dir / "avatars"
    avatars_dir.mkdir(parents=True, exist_ok=True)
    key = f"avatars/{user.id}-{int(time.time())}.{ext}"
    (settings.data_dir / key).write_bytes(data)
    previous = user.avatar_key
    user.avatar_key = key
    db.commit()
    # 旧文件在提交成功后清理;失败也只是留一个孤儿文件,不影响正确性。
    if previous and previous.startswith("avatars/"):
        (settings.data_dir / previous).unlink(missing_ok=True)
    db.refresh(user)
    return UserOut.model_validate(user)


@router.get("/auth/users/{user_id}/avatar")
def get_user_avatar(user_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    """任何已登录用户可取(团队页/成员列表要显示彼此头像)。<img> 带不了请求头,
    走与素材文件同款的 ?token= 查询参数鉴权(CurrentUser 依赖两者都认)。"""
    target = db.get(User, user_id)
    key = (target.avatar_key if target else "") or ""
    # key 只能落在 avatars/ 下,防目录穿越(库里即便被改坏也不放行)。
    if not key.startswith("avatars/") or "/../" in key or key.endswith(".."):
        raise HTTPException(status_code=404, detail="No avatar")
    path = settings.data_dir / key
    if not path.is_file():
        raise HTTPException(status_code=404, detail="No avatar")
    media_type = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}.get(path.suffix.lstrip("."), "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=86400"})


@router.post("/auth/me/password")
def update_password(body: PasswordUpdate, db: DbSession, user: CurrentUser) -> dict:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}


@router.post("/auth/logout")
def logout(request: Request, db: DbSession, user: CurrentUser) -> dict:
    # Read the token the same way get_current_user does. Reading only the header meant logging
    # out of a ?token= session reported success and revoked nothing — a false confirmation,
    # which is worse than refusing.
    header = request.headers.get("authorization", "")
    token = header.removeprefix("Bearer ").strip() or (request.query_params.get("token") or "").strip()
    session = db.get(AuthSession, token) if token else None
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
    # commit=False:注册时用户行和会话行要么一起进库,要么都不进(调用方紧接着 commit)。
    return mint_login_session(db, user.id, commit=False)


def _normalize_username(value: str) -> str:
    return value.strip().lower()


def _clean_display_name(value: str, username: str) -> str:
    return value.strip() or username


def _adopt_orphan_workspaces(db: DbSession, user: User) -> None:
    """Local upgrade path: the first account inherits pre-auth workspaces."""
    members_exist = db.scalar(select(WorkspaceMember).limit(1))
    if members_exist is not None:
        return
    for workspace in db.scalars(select(Workspace)):
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
