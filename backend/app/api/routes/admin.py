from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy import func, select

from app.core.i18n import tr
from app.core.outbound_guard import AllowlistError
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import AdminOverviewOut, AdminUserOut
from app.domain.permissions import ensure_deployment_admin
from app.domain import dashboard, deployment, host_files, members, outbound_allowlist
from app.db.models import AuthSession, User, WorkspaceMember

router = APIRouter(tags=["admin"])

"""管理员控制台:**这台部署**的状况。

和「设置」是两件事,所以不挤在设置页里:设置回答"我怎么用这个应用"(外观、我的密钥、我的默认
模型);这里回答"这台部署怎么样"—— 谁进来了、谁在花钱、谁的客户端还停在旧版本。

整条路由都在 `ensure_deployment_admin` 后面:普通成员连列表都取不到,前端也据此决定要不要
在侧边栏摆这个入口。
"""

@router.get("/admin/users", response_model=list[AdminUserOut])
def list_users(db: DbSession, user: CurrentUser) -> list[AdminUserOut]:
    """这个部署里的人:身份、最近在用吗、跑的是哪一版。

    版本取他**最近一次**用到的那份凭据上报的 —— 一个人可以同时开着桌面端和网页端,而管理员
    要回答的是"他现在跑的是哪一版"。
    """
    ensure_deployment_admin(db, user)
    people = db.scalars(select(User).order_by(User.created_at)).all()
    latest: dict[str, AuthSession] = {}
    for session in db.scalars(select(AuthSession).order_by(AuthSession.last_seen_at)):
        if session.last_seen_at is not None:
            latest[session.user_id] = session  # 按 last_seen 升序,最后一条即最新
    counts = dict(
        db.execute(
            select(WorkspaceMember.user_id, func.count()).group_by(WorkspaceMember.user_id)
        ).all()
    )
    return [
        AdminUserOut(
            id=person.id,
            username=person.username,
            display_name=person.display_name,
            is_deployment_admin=person.is_deployment_admin,
            created_at=person.created_at,
            last_seen_at=latest[person.id].last_seen_at if person.id in latest else None,
            client_version=latest[person.id].client_version if person.id in latest else "",
            client_surface=latest[person.id].client_surface if person.id in latest else "",
            workspaces=int(counts.get(person.id, 0)),
        )
        for person in people
    ]


@router.delete("/admin/users/{user_id}", status_code=204)
def delete_user(user_id: str, db: DbSession, user: CurrentUser) -> Response:
    """删掉一个账号,以及只属于他的那些东西(见 domain/members.delete_account)。

    此前没有这条路:管理页能授予、能收回部署管理员,却删不掉一个账号 —— 于是"清理掉那个测试
    账号"只能去手改数据库,而手改必然漏(有些指向人的列有意不设外键)。
    """
    ensure_deployment_admin(db, user)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail=tr("routeErr_accountNotFound"))
    try:
        members.delete_account(db, target)
    except members.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)


class RegistrationSwitch(BaseModel):
    open: bool


@router.put("/admin/registration")
def set_registration(body: RegistrationSwitch, db: DbSession, user: CurrentUser) -> dict:
    """开关自助注册。**谁能进这个部署**是部署级的决定 —— 和发邀请码、授予管理员同一类。"""
    ensure_deployment_admin(db, user)
    deployment.set_open_registration(db, body.open)
    db.commit()
    return {"open": deployment.open_registration(db)}


class SharedHostFolders(BaseModel):
    folders: list[str]


@router.get("/admin/shared-host-folders", response_model=SharedHostFolders)
def get_shared_host_folders(db: DbSession, user: CurrentUser) -> SharedHostFolders:
    """管理员共享给成员的本机文件夹。

    **登录就能读**,不只管理员:这份清单本来就是给成员用的 —— 工作流里填本机路径被挡下时,
    他要知道该把文件放到哪儿。改它才是部署管理员的事。
    """
    return SharedHostFolders(folders=host_files.shared_folders(db))


@router.put("/admin/shared-host-folders", response_model=SharedHostFolders)
def set_shared_host_folders(body: SharedHostFolders, db: DbSession, user: CurrentUser) -> SharedHostFolders:
    """这台电脑上哪些文件夹共享给成员读(见 domain/host_files)。和开放注册同一类:部署级的决定。"""
    ensure_deployment_admin(db, user)
    try:
        folders = host_files.set_shared_folders(db, body.folders)
    except host_files.HostFileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return SharedHostFolders(folders=folders)


class OutboundAllowlist(BaseModel):
    entries: list[str]


@router.get("/admin/outbound-allowlist", response_model=OutboundAllowlist)
def get_outbound_allowlist(db: DbSession, user: CurrentUser) -> OutboundAllowlist:
    """用户给的地址(HTTP 请求节点、智能体的 http_request / fetch_url、从链接导入)可以去的内网地址。

    **只给管理员看**:这份清单就是一张内网地图(哪台 NAS、哪个端口有服务)。成员被拦下时,报错里已经说了该加哪一项、
    找谁加(见 core/outbound_guard)。
    """
    ensure_deployment_admin(db, user)
    return OutboundAllowlist(entries=outbound_allowlist.entries(db))


@router.put("/admin/outbound-allowlist", response_model=OutboundAllowlist)
def set_outbound_allowlist(body: OutboundAllowlist, db: DbSession, user: CurrentUser) -> OutboundAllowlist:
    """改内网访问的允许名单。和共享文件夹同一类:部署级的决定。"""
    ensure_deployment_admin(db, user)
    try:
        entries = outbound_allowlist.save(db, body.entries)
    except AllowlistError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return OutboundAllowlist(entries=entries)


@router.get("/admin/overview", response_model=AdminOverviewOut)
def overview(
    db: DbSession,
    user: CurrentUser,
    # 窗口的默认值和上限与统计页是同一套(`domain/dashboard`):两页上的「近 N 天」是同一个意思。
    days: int = Query(default=dashboard.WINDOW_DAYS, ge=1, le=dashboard.MAX_WINDOW_DAYS),
) -> AdminOverviewOut:
    """这一页顶部的几个数,加上两张图。

    **花销按人分**,不是只给一个总数:管理员要回答的是"谁在花" —— 一个总数说明不了任何该做的
    决定,而按人分的那一列直接指向要谈的那个人。

    `days` 是两张图(任务活动、按人花费)的窗口:今天加上前 `days - 1` 天,从那天的零点(UTC)
    算起。账户、工作区、素材是当前总数,不受它影响。
    """
    ensure_deployment_admin(db, user)
    return AdminOverviewOut(**dashboard.deployment_overview(db, days=days))
