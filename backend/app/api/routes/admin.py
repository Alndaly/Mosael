from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.i18n import tr
from app.core.outbound_guard import AllowlistError
from app.api.deps import CurrentUser, DbSession, Tx
from app.api.routes.workspaces import invite_link_out, issued_out
from app.api.schemas import (
    AdminOverviewOut,
    AdminPasswordResetOut,
    AdminUserOut,
    InviteCreate,
    InviteLinkOut,
    IssuedInviteLinkOut,
    WebUrlUpdate,
)
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


@router.post("/admin/users/{user_id}/password", response_model=AdminPasswordResetOut)
def reset_user_password(user_id: str, db: Tx, user: CurrentUser) -> AdminPasswordResetOut:
    """替一个成员重置密码:生成一个临时密码(只在这一次给出),他已经登录着的会话全部作废(见 members.reset_password)。

    忘了密码的人此前只能被删号重来。改自己的密码走「设置 → 账户」(要旧密码) —— 在这里重置自己会把自己踢下线。
    """
    ensure_deployment_admin(db, user)
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail=tr("routeErr_accountNotFound"))
    if target.id == user.id:
        raise HTTPException(status_code=409, detail=tr("routeErr_resetOwnPassword"))
    return AdminPasswordResetOut(password=members.reset_password(db, target))


class RegistrationSwitch(BaseModel):
    open: bool


@router.put("/admin/registration")
def set_registration(body: RegistrationSwitch, db: DbSession, user: CurrentUser) -> dict:
    """开关自助注册。**谁能进这个部署**是部署级的决定 —— 和发邀请码、授予管理员同一类。"""
    ensure_deployment_admin(db, user)
    deployment.set_open_registration(db, body.open)
    db.commit()
    return {"open": deployment.open_registration(db)}


# ---------------- 邀请(ADR 0054) ----------------


@router.post("/admin/invite-links", response_model=IssuedInviteLinkOut)
def create_deployment_invite(body: InviteCreate, db: Tx, user: CurrentUser) -> IssuedInviteLinkOut:
    """发一张**不带工作区**的邀请:只进这台部署(此前的「注册邀请码」)。对方注册完自己建工作区,或者再被人拉进去。

    「谁能放人进这个部署」和「谁对这个部署负责」是同一件事,所以判据就是部署管理员那一列。原文只在这一次。
    """
    ensure_deployment_admin(db, user)
    return issued_out(db, members.issue_invite_link(db, user, workspace_id=None, note=body.note))


@router.get("/admin/invite-links", response_model=list[InviteLinkOut])
def list_deployment_invites(db: DbSession, user: CurrentUser) -> list[InviteLinkOut]:
    """不带工作区的邀请(含升级前发出去的注册邀请码,迁移时并进来了,照样用到过期)。最近 50 张。"""
    ensure_deployment_admin(db, user)
    return [invite_link_out(db, link) for link in members.deployment_links(db)]


@router.delete("/admin/invite-links/{link_id}", status_code=204)
def revoke_deployment_invite(link_id: str, db: Tx, user: CurrentUser) -> Response:
    """作废一张还没用过的不带工作区的邀请。用过的留着 —— 它记着这个账号是凭谁发的邀请进来的。"""
    ensure_deployment_admin(db, user)
    try:
        members.revoke_invite_link(db, link_id, workspace_id=None)
    except members.MemberError as exc:
        status = 404 if exc.key == "memberErr_linkUnknown" else 409
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/admin/invite-links/awaiting-signup", response_model=list[InviteLinkOut])
def invites_awaiting_signup(db: DbSession, user: CurrentUser) -> list[InviteLinkOut]:
    """工作区管理员请你放行的邀请链接:放行之后,还没账号的人也能凭它注册(ADR 0054 D48)。"""
    ensure_deployment_admin(db, user)
    return [invite_link_out(db, link) for link in members.links_awaiting_signup(db)]


@router.post("/admin/invite-links/{link_id}/approve-signup", response_model=InviteLinkOut)
def approve_invite_signup(link_id: str, db: Tx, user: CurrentUser) -> InviteLinkOut:
    ensure_deployment_admin(db, user)
    try:
        return invite_link_out(db, members.approve_signup(db, link_id, admin=user))
    except members.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.put("/admin/web-url", response_model=WebUrlUpdate)
def set_web_url(body: WebUrlUpdate, db: Tx, user: CurrentUser) -> WebUrlUpdate:
    """部署的网页地址:成员用浏览器打开 Mosael 的地方。填了,邀请链接就带一个网页地址(ADR 0054 D52)。"""
    ensure_deployment_admin(db, user)
    url = body.url.strip().rstrip("/")
    if url and not url.lower().startswith(("https://", "http://")):
        raise HTTPException(status_code=422, detail=tr("routeErr_webUrlScheme"))
    deployment.set_web_url(db, url)
    db.flush()
    return WebUrlUpdate(url=deployment.web_url(db))


class JobRetention(BaseModel):
    #: 结束多少天的任务行由保留清理删掉:90 / 180 / 365(deployment.JOB_RETENTION_CHOICES);`null` = 永久保留(ADR 0050 D29)。
    days: int | None


@router.get("/admin/job-retention", response_model=JobRetention)
def get_job_retention(db: DbSession, user: CurrentUser) -> JobRetention:
    """任务行保留多久。只给部署管理员:和备份、恢复同一类,是这台部署的数据怎么留。"""
    ensure_deployment_admin(db, user)
    return JobRetention(days=deployment.job_retention_days(db))


@router.put("/admin/job-retention", response_model=JobRetention)
def set_job_retention(body: JobRetention, db: Tx, user: CurrentUser) -> JobRetention:
    """改保留天数。被定时任务运行、生成记录、发布记录指着的和记过用量的任务不删;删的那一刻在后台的保留清理里。"""
    ensure_deployment_admin(db, user)
    try:
        deployment.set_job_retention_days(db, body.days)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=tr("routeErr_jobRetentionChoice")) from exc
    db.flush()
    return JobRetention(days=deployment.job_retention_days(db))


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


class StorageOrphanOut(BaseModel):
    key: str
    reason: str
    bytes: int
    modified_at: datetime


class StorageOrphansOut(BaseModel):
    items: list[StorageOrphanOut]
    total_bytes: int


class StorageOrphanDelete(BaseModel):
    keys: list[str] = Field(min_length=1, max_length=10_000)


class StorageOrphanDeleteOut(BaseModel):
    deleted: list[str]
    skipped: list[str]


@router.get("/admin/storage/orphans", response_model=StorageOrphansOut)
def list_storage_orphans(db: DbSession, user: CurrentUser) -> StorageOrphansOut:
    """数据目录里没人认领的文件:工作区 / 素材 / 音色 / LUT / 字体已经删了、文件还在的,没有账号在用的头像。
    **只列,不删**(见 domain/storage_cleanup:判据是此刻库里没有对应的行,而那可能是恢复到一半的库)。"""
    ensure_deployment_admin(db, user)
    from app.domain.storage_cleanup import find_orphans

    items = [StorageOrphanOut(**vars(one)) for one in find_orphans(db)]
    return StorageOrphansOut(items=items, total_bytes=sum(one.bytes for one in items))


@router.post("/admin/storage/orphans/delete", response_model=StorageOrphanDeleteOut)
def delete_storage_orphans(body: StorageOrphanDelete, db: DbSession, user: CurrentUser) -> StorageOrphanDeleteOut:
    """删掉管理员看过、勾选的那些孤儿。删之前再判一遍:此刻已经有人认领、或者不在清单里的一律跳过。"""
    ensure_deployment_admin(db, user)
    from app.domain.storage_cleanup import delete_orphans

    deleted, skipped = delete_orphans(db, body.keys)
    return StorageOrphanDeleteOut(deleted=deleted, skipped=skipped)


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
