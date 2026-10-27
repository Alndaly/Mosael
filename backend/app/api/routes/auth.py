from __future__ import annotations


from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from app.api.responses import file_response
from sqlalchemy.orm import Session

from app.core.i18n import tr
from app.api.deps import CurrentUser, DbSession, PresentedToken
from app.api.schemas import (
    AuthCredentials,
    AuthOut,
    BootstrapOut,
    DeploymentAdminUpdate,
    InviteCodeIn,
    InviteLinkPreviewOut,
    PasswordUpdate,
    RegisterCredentials,
    UserOut,
    UserProfileUpdate,
)
from app.core.security import (
    find_session,
    mint_login_session,
)
from app.domain import accounts, deployment, members
from app.db.models import User

router = APIRouter(tags=["auth"])


def current_user_out(db: Session, user: User) -> UserOut:
    """**我**这个账号交给界面的样子 —— 登录、注册、第三方登录取票、/me 及其改动都从这里出。

    多一步查询是因为「怎么登进来的」不在 users 行上,在 oauth_identities 里。各出口各写一遍
    model_validate 的话,漏掉的那个出口就会把一个 Google 账号报成密码账号(第三方登录取票
    此前就只回三个字段,头像要到下次启动才出现)。
    """
    return UserOut.model_validate(user).model_copy(update={"oauth_providers": accounts.login_providers(db, user)})


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


@router.post("/auth/invite-links/preview", response_model=InviteLinkPreviewOut)
def preview_invite_link(body: InviteCodeIn, db: DbSession) -> InviteLinkPreviewOut:
    """打开一张邀请链接、还没登录的那一屏:进哪个工作区、谁邀请的、还能不能用、没账号的人能不能凭它注册
    (ADR 0054)。**不需要登录** —— 拿着原文的人就是被邀请的人;码在请求体里,不进访问日志。"""
    preview = members.preview_invite_link(db, body.code)
    if preview is None:
        raise HTTPException(status_code=404, detail=tr("memberErr_linkUnknown"))
    return InviteLinkPreviewOut(**preview)


@router.get("/auth/users")
def list_deployment_users(db: DbSession, user: CurrentUser) -> list[dict]:
    """这个部署里的所有账号。给部署管理员用 —— 授予/收回那一列需要知道有谁。

    只有部署管理员能看:成员名单在工作区里各自可见,而**跨工作区的全量名单**是部署级信息。
    """
    return accounts.deployment_users(db, user)


@router.post("/auth/users/{user_id}/deployment-admin")
def set_deployment_admin(user_id: str, body: DeploymentAdminUpdate, db: DbSession, user: CurrentUser) -> dict:
    """授予 / 收回「部署管理员」。只有部署管理员能改 —— 能自己给自己发就又回到自助了。

    最后一个部署管理员不能被收回:没有他,实例配置改不了、注册邀请码也发不出来,这个部署就成了
    一块砖头,而且**没有任何应用内的路可以救回来**。
    """
    try:
        target = accounts.set_deployment_admin(db, user, user_id, granted=body.granted)
    except accounts.LastDeploymentAdmin as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")
    db.commit()
    return {"user_id": target.id, "is_deployment_admin": target.is_deployment_admin}


@router.post("/auth/login", response_model=AuthOut)
def login(body: AuthCredentials, db: DbSession) -> AuthOut:
    user = accounts.authenticate(db, body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")
    token = _create_session(db, user)
    db.commit()
    return AuthOut(token=token, user=current_user_out(db, user))


@router.get("/auth/me", response_model=UserOut)
def me(db: DbSession, user: CurrentUser) -> UserOut:
    return current_user_out(db, user)


@router.patch("/auth/me", response_model=UserOut)
def update_me(body: UserProfileUpdate, db: DbSession, user: CurrentUser) -> UserOut:
    try:
        accounts.update_profile(
            db, user, username=body.username, display_name=body.display_name, signature=body.signature
        )
    except members.UsernameTaken as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    db.refresh(user)
    return current_user_out(db, user)


@router.post("/auth/me/avatar", response_model=UserOut)
def upload_avatar(db: DbSession, user: CurrentUser, file: UploadFile = File(...)) -> UserOut:
    """上传/替换头像:落 data_dir/avatars/<uid>-<ts>.<ext>,key 带时间戳天然破缓存。

    同步端点(跑在线程池里):写盘和数据库都是阻塞调用,放在 async 里会卡住事件循环。"""
    #: 多读一个字节就知道超没超,不必整份读进来。
    data = file.file.read(accounts.AVATAR_MAX_BYTES + 1)
    try:
        accounts.set_avatar(db, user, content_type=file.content_type or "", data=data)
    except accounts.AvatarRejected as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc
    db.commit()
    db.refresh(user)
    return current_user_out(db, user)


@router.get("/auth/users/{user_id}/avatar")
def get_user_avatar(user_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    """任何已登录用户可取(团队页/成员列表要显示彼此头像)。<img> 带不了请求头,
    走与素材文件同款的 ?token= 查询参数鉴权(CurrentUser 依赖两者都认)。"""
    found = accounts.avatar_file(db, user_id)
    if found is None:
        raise HTTPException(status_code=404, detail="No avatar")
    path, media_type = found
    return file_response(db, path, media_type=media_type, headers={"Cache-Control": "private, max-age=86400"})


@router.post("/auth/me/password")
def update_password(body: PasswordUpdate, db: DbSession, user: CurrentUser, token: PresentedToken) -> dict:
    """改密码,并把这个人**别处的登录**都踢下线(当前这一份留着,改完不用重新登录)。"""
    try:
        signed_out = accounts.change_password(db, user, current=body.current_password, new=body.new_password, keep=token)
    except accounts.WrongPassword as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    db.commit()
    return {"ok": True, "signed_out": signed_out}


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
    return BootstrapOut(
        has_users=accounts.has_users(db), open_registration=deployment.open_registration(db), web_url=deployment.web_url(db)
    )


def _create_session(db: DbSession, user: User) -> str:
    # commit=False:注册时用户行和会话行要么一起进库,要么都不进(调用方紧接着 commit)。
    return mint_login_session(db, user.id, commit=False)
