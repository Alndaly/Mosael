from __future__ import annotations

import time
from datetime import timedelta

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.i18n import tr
from app.api.deps import CurrentUser, DbSession, PresentedToken
from app.api.schemas import (
    AuthCredentials,
    AuthOut,
    BootstrapOut,
    DeploymentAdminUpdate,
    InviteCreate,
    PasswordUpdate,
    RegisterCredentials,
    UserOut,
    UserProfileUpdate,
)
from app.core.config import settings
from app.domain.permissions import ensure_deployment_admin
from app.core.security import find_session, hash_password, mint_login_session, new_session_token, verify_password
from app.domain import deployment, members
from app.db.models import OAuthIdentity, RegistrationInvite, User, now

router = APIRouter(tags=["auth"])

#: 邀请码的有效期。够对方从收到消息到坐下来注册,又不至于长期挂在那儿。
INVITE_TTL = timedelta(days=7)


def current_user_out(db: Session, user: User) -> UserOut:
    """**我**这个账号交给界面的样子 —— 登录、注册、第三方登录取票、/me 及其改动都从这里出。

    多一步查询是因为「怎么登进来的」不在 users 行上,在 oauth_identities 里。各出口各写一遍
    model_validate 的话,漏掉的那个出口就会把一个 Google 账号报成密码账号(第三方登录取票
    此前就只回三个字段,头像要到下次启动才出现)。
    """
    providers = db.scalars(
        select(OAuthIdentity.provider).where(OAuthIdentity.user_id == user.id).order_by(OAuthIdentity.created_at)
    ).all()
    return UserOut.model_validate(user).model_copy(update={"oauth_providers": list(providers)})


@router.post("/auth/register", response_model=AuthOut)
def register(body: RegisterCredentials, db: DbSession) -> AuthOut:
    """注册。**引导之后转邀请制** —— 见 ADR 0008 §0。

    这是个多租户产品:一个后端可以服务多个人,而开放注册让「任何能连到这个端口的人」直接成为
    里面的一个租户。那正是下面这条(跑出来过的)链的第一环:

        注册 → 自己建一个工作区(在里面是 owner)→ 满足当时那道自助的实例管理员判据
             → 改实例配置 / 存 code 节点 → 在服务端执行任意 Python

    空库时照常放行:那时没有任何人可以给第一个账号发邀请。之后只能由已有成员邀请
    (见 workspaces 的 invitations 路由),想保持开放的部署显式打开 MOSAEL_OPEN_REGISTRATION。
    闸门、首个账号的引导都在 domain/members.create_account —— 第三方登录建号走的是同一个。
    """
    try:
        user = members.create_account(
            db,
            username=body.username,
            display_name=body.display_name,
            password=body.password,
            invite_code=body.invite_code,
        )
    except members.SignupClosed as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except members.UsernameTaken as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    token = _create_session(db, user)
    db.commit()
    return AuthOut(token=token, user=current_user_out(db, user))


@router.post("/auth/invites")
def create_registration_invite(body: InviteCreate, db: DbSession, user: CurrentUser) -> dict:
    """发一个进这个部署的邀请码。带外发给对方,对方拿它注册并自己设密码。

    「谁能放人进这个部署」和「谁对这个部署负责」是同一件事,所以判据就是部署管理员那一列。
    """
    ensure_deployment_admin(db, user)
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
    ensure_deployment_admin(db, user)
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


@router.get("/auth/users")
def list_deployment_users(db: DbSession, user: CurrentUser) -> list[dict]:
    """这个部署里的所有账号。给部署管理员用 —— 授予/收回那一列需要知道有谁。

    只有部署管理员能看:成员名单在工作区里各自可见,而**跨工作区的全量名单**是部署级信息。
    """
    ensure_deployment_admin(db, user)
    rows = db.scalars(select(User).order_by(User.created_at.asc()))
    return [
        {
            "id": row.id,
            "username": row.username,
            "display_name": row.display_name,
            "is_deployment_admin": row.is_deployment_admin,
        }
        for row in rows
    ]


@router.post("/auth/users/{user_id}/deployment-admin")
def set_deployment_admin(user_id: str, body: DeploymentAdminUpdate, db: DbSession, user: CurrentUser) -> dict:
    """授予 / 收回「部署管理员」。只有部署管理员能改 —— 能自己给自己发就又回到自助了。

    最后一个部署管理员不能被收回:没有他,实例配置改不了、注册邀请码也发不出来,这个部署就成了
    一块砖头,而且**没有任何应用内的路可以救回来**。
    """
    ensure_deployment_admin(db, user)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")
    if not body.granted:
        others = db.scalar(
            select(func.count())
            .select_from(User)
            .where(User.is_deployment_admin.is_(True), User.id != target.id)
        )
        if not others:
            raise HTTPException(status_code=409, detail=tr("routeErr_lastDeploymentAdmin"))
    target.is_deployment_admin = bool(body.granted)
    db.commit()
    return {"user_id": target.id, "is_deployment_admin": target.is_deployment_admin}


@router.post("/auth/login", response_model=AuthOut)
def login(body: AuthCredentials, db: DbSession) -> AuthOut:
    user = db.scalar(select(User).where(User.username == members.normalize_username(body.username)))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = _create_session(db, user)
    db.commit()
    return AuthOut(token=token, user=current_user_out(db, user))


@router.get("/auth/me", response_model=UserOut)
def me(db: DbSession, user: CurrentUser) -> UserOut:
    return current_user_out(db, user)


@router.patch("/auth/me", response_model=UserOut)
def update_me(body: UserProfileUpdate, db: DbSession, user: CurrentUser) -> UserOut:
    username = members.normalize_username(body.username)
    if username != user.username:
        existing = db.scalar(select(User).where(User.username == username, User.id != user.id))
        if existing is not None:
            raise HTTPException(status_code=409, detail=tr("memberErr_usernameTaken"))
    user.username = username
    user.display_name = body.display_name.strip() or username
    user.signature = body.signature.strip()
    db.commit()
    db.refresh(user)
    return current_user_out(db, user)


_AVATAR_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}
_AVATAR_MAX_BYTES = 4 * 1024 * 1024


@router.post("/auth/me/avatar", response_model=UserOut)
async def upload_avatar(db: DbSession, user: CurrentUser, file: UploadFile = File(...)) -> UserOut:
    """上传/替换头像:落 data_dir/avatars/<uid>-<ts>.<ext>,key 带时间戳天然破缓存。"""
    ext = _AVATAR_TYPES.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(status_code=415, detail=tr("routeErr_avatarType"))
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail=tr("routeErr_emptyFile"))
    if len(data) > _AVATAR_MAX_BYTES:
        raise HTTPException(status_code=413, detail=tr("routeErr_avatarTooLarge"))
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
    return current_user_out(db, user)


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
def logout(db: DbSession, user: CurrentUser, token: PresentedToken) -> dict:
    # Read the token the same way get_current_user does (PresentedToken is that same reader).
    # Reading only the header meant logging out of a ?token= session reported success and
    # revoked nothing — a false confirmation, which is worse than refusing.
    session = find_session(db, token)
    if session is not None and session.user_id == user.id:
        db.delete(session)
        db.commit()
    return {"ok": True}


@router.get("/auth/bootstrap", response_model=BootstrapOut)
def bootstrap(db: DbSession) -> BootstrapOut:
    """登录页开屏要知道的两件事:**这个部署里有人了吗**、**收不收自助注册**。

    不需要登录 —— 这就是登录之前那一屏在问的。只回两个布尔,不泄露任何账号信息;而"库里有没有
    人"本来就能从"不带邀请码注册能不能成"推出来。

    没人 → 界面进「创建管理员账户」:那时没有任何人可以发邀请,而没有部署管理员的部署是块砖头。
    """
    count = db.scalar(select(func.count()).select_from(User)) or 0
    return BootstrapOut(has_users=count > 0, open_registration=deployment.open_registration(db))


def _create_session(db: DbSession, user: User) -> str:
    # commit=False:注册时用户行和会话行要么一起进库,要么都不进(调用方紧接着 commit)。
    return mint_login_session(db, user.id, commit=False)
