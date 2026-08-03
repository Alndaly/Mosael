from __future__ import annotations

import time
from datetime import timedelta

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import AuthCredentials, AuthOut, InviteCreate, PasswordUpdate, RegisterCredentials, UserOut, UserProfileUpdate
from app.core.config import settings
from app.core.security import hash_password, mint_login_session, new_session_token, verify_password
from app.db.models import AuthSession, RegistrationInvite, User, Workspace, WorkspaceMember, now

router = APIRouter(tags=["auth"])

#: 邀请码的有效期。够对方从收到消息到坐下来注册,又不至于长期挂在那儿。
INVITE_TTL = timedelta(days=7)


@router.post("/auth/register", response_model=AuthOut)
def register(body: RegisterCredentials, db: DbSession) -> AuthOut:
    """注册。**引导之后转邀请制** —— 见 ADR 0008 §0。

    这是个多租户产品:一个后端可以服务多个人,而开放注册让「任何能连到这个端口的人」直接成为
    里面的一个租户。那正是下面这条(跑出来过的)链的第一环:

        注册 → 自己建一个工作区(在里面是 owner)→ 满足 ensure_instance_admin
             → 改实例配置 / 存 code 节点 → 在服务端执行任意 Python

    空库时照常放行:那时没有任何人可以给第一个账号发邀请。之后只能由已有成员邀请
    (见 workspaces 的 invitations 路由),想保持开放的部署显式打开 OPEN_STUDIO_OPEN_REGISTRATION。
    """
    invite = _usable_invite(db, body.invite_code)
    if not settings.open_registration and invite is None and db.scalar(select(User).limit(1)) is not None:
        raise HTTPException(
            status_code=403,
            detail="这个部署不开放自助注册,请向管理员要一个邀请码",
        )
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
    if invite is not None:
        invite.used_by = user.id  # 一次性:同一个码不能再换第二个账号
    token = _create_session(db, user)
    db.commit()
    return AuthOut(token=token, user=UserOut.model_validate(user))


def _is_bootstrap_account(db: DbSession, user: User) -> bool:
    """他是不是引导这个部署的那个账号(库里最早创建的)。第 1 步用一列取代它。"""
    first = db.scalar(select(User).order_by(User.created_at.asc(), User.id.asc()).limit(1))
    return first is not None and first.id == user.id


def _usable_invite(db: DbSession, code: str) -> RegistrationInvite | None:
    """还能用的注册邀请码:存在、没用过、没过期。看不懂的码一律当作没有。"""
    code = (code or "").strip()
    if not code:
        return None
    invite = db.get(RegistrationInvite, code)
    if invite is None or invite.used_by or invite.expires_at <= now():
        return None
    return invite


@router.post("/auth/invites")
def create_registration_invite(body: InviteCreate, db: DbSession, user: CurrentUser) -> dict:
    """发一个进这个部署的邀请码。带外发给对方,对方拿它注册并自己设密码。

    判据是「你是不是引导这个部署的那个账号」。**不用 ensure_instance_admin** —— 那道闸恰恰是自助的
    (ADR 0008 §2.1),拿它守发码等于没守;而且它要求你在某个工作区里是 admin,引导账号可能还没建
    过工作区,连自己都发不出码。

    第 1 步会把这个事实落成 `users.is_deployment_admin` 一列,那时这个函数改成读那一列 ——
    语义不变,只是从「按创建时间猜」变成「按数据说」。
    """
    if not _is_bootstrap_account(db, user):
        raise HTTPException(status_code=403, detail="只有引导这个部署的账号可以发注册邀请码")
    invite = RegistrationInvite(
        code=new_session_token()[:32],
        created_by=user.id,
        note=body.note.strip()[:120],
        expires_at=now() + INVITE_TTL,
    )
    db.add(invite)
    db.commit()
    return {"code": invite.code, "note": invite.note, "expires_at": invite.expires_at.isoformat()}


@router.get("/auth/invites")
def list_registration_invites(db: DbSession, user: CurrentUser) -> list[dict]:
    if not _is_bootstrap_account(db, user):
        raise HTTPException(status_code=403, detail="只有引导这个部署的账号可以查看注册邀请码")
    rows = db.scalars(select(RegistrationInvite).order_by(RegistrationInvite.created_at.desc()).limit(50))
    return [
        {
            "code": row.code,
            "note": row.note,
            "used": bool(row.used_by),
            "expires_at": row.expires_at.isoformat(),
        }
        for row in rows
    ]


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
