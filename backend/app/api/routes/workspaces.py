from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from app.core.i18n import tr
from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas import (
    InviteCodeIn,
    InviteLinkCreate,
    InviteLinkJoinedOut,
    InviteLinkOut,
    InviteMemberRequest,
    IssuedInviteLinkOut,
    MembersOut,
    RenameRequest,
    SetRoleRequest,
    WorkspaceCreate,
    WorkspaceMemberOut,
    WorkspaceOut,
    WorkspaceSummaryOut,
    InvitationOut,
    InvitationListOut,
)
from sqlalchemy.orm import Session

from app.db.models import InviteLink, User, Workspace
from app.domain import dashboard, deployment, members as members_svc
from app.domain.workspaces import use_cases as workspaces

router = APIRouter(tags=["workspaces"])


@router.post("/workspaces", response_model=WorkspaceOut)
def create_workspace(body: WorkspaceCreate, db: Tx, user: CurrentUser) -> WorkspaceOut:
    workspace = workspaces.create_workspace(db, user, body.name)
    return WorkspaceOut(id=workspace.id, name=workspace.name, role="owner")


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(db: DbSession, user: CurrentUser) -> list[WorkspaceOut]:
    return [WorkspaceOut(id=ws.id, name=ws.name, role=role) for ws, role in members_svc.workspaces_of(db, user.id)]


@router.patch("/workspaces/{workspace_id}")
def rename_workspace(workspace_id: str, body: RenameRequest, db: Tx, user: CurrentUser) -> dict:
    workspace = workspaces.rename_workspace(db, user, workspace_id, body.name)
    return {"id": workspace.id, "name": workspace.name}


class AutopilotRulesBody(BaseModel):
    rules: dict = {}


@router.get("/workspaces/{workspace_id}/autopilot-rules")
def get_autopilot_rules(workspace_id: str, db: DbSession, user: CurrentUser) -> dict:
    """auto 档下 `external` 的放行准则(见 domain/agent/rules)。读:工作区成员即可。"""
    return {"rules": workspaces.autopilot_rules_of(db, user, workspace_id)}


@router.put("/workspaces/{workspace_id}/autopilot-rules")
def set_autopilot_rules(workspace_id: str, body: AutopilotRulesBody, db: Tx, user: CurrentUser) -> dict:
    """改准则要 admin。

    它决定的是「什么可以不问就发出去」—— 往主机白名单里加一行,等于让智能体从此可以不经确认
    对那个地址发写请求。这和开 bypass 是同一级别的授权动作,不该是每个编辑都能改的。
    """
    return {"rules": workspaces.set_autopilot_rules(db, user, workspace_id, body.rules)}


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, db: Tx, user: CurrentUser) -> Response:
    workspaces.delete_workspace(db, user, workspace_id)
    return Response(status_code=204)


class PoemOut(BaseModel):
    """首页那句诗。取不到时前端回落本地精选 —— 断网不该让首页空一格。"""

    text: str
    author: str = ""
    source: str = ""
    dynasty: str = ""


@router.get("/home/poem", response_model=PoemOut)
def get_home_poem(user: CurrentUser) -> PoemOut:
    """向今日诗词取一句。走后端是为了吃到出站代理、并且 token 只换一次(见 domain/poem)。"""
    from app.domain.poem import PoemUnavailable, fetch_poem

    try:
        poem = fetch_poem()
    except (PoemUnavailable, Exception) as exc:  # noqa: BLE001 — 取不到是正常结果,前端有本地兜底
        raise HTTPException(status_code=502, detail=tr("routeErr_poemUnreachable", detail=str(exc))) from exc
    return PoemOut(text=poem.text, author=poem.author, source=poem.source, dynasty=poem.dynasty)


@router.get("/workspaces/{workspace_id}/members", response_model=MembersOut)
def list_members(workspace_id: str, db: DbSession, user: CurrentUser) -> MembersOut:
    my_role, rows = workspaces.members_of(db, user, workspace_id)
    members = [
        WorkspaceMemberOut(
            user_id=member_user.id,
            username=member_user.username,
            display_name=member_user.display_name,
            role=member.role,
            is_self=member_user.id == user.id,
        )
        for member_user, member in rows
    ]
    return MembersOut(
        members=members,
        my_role=my_role,
    )


@router.post("/workspaces/{workspace_id}/invitations", response_model=InvitationOut)
def invite_member(workspace_id: str, body: InviteMemberRequest, db: Tx, user: CurrentUser) -> InvitationOut:
    """邀请制:只对已注册用户名发邀请,对方在通知里接受后才建成员行。"""
    try:
        invitee, invitation, workspace_name = workspaces.invite_to_workspace(
            db, user, workspace_id, body.username, body.role
        )
    except members_svc.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return InvitationOut(
        id=invitation.id,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        inviter_name=user.display_name,
        invitee_name=invitee.display_name,
        role=invitation.role,
        status=invitation.status,
        created_at=invitation.created_at,
    )


@router.get("/workspaces/{workspace_id}/invitations", response_model=InvitationListOut)
def sent_invitations(workspace_id: str, db: DbSession, user: CurrentUser) -> InvitationListOut:
    """这个工作区发出去、对方还没应答的邀请(团队页列在成员下面,能撤回)。"""
    workspace = db.get(Workspace, workspace_id)
    items = [
        InvitationOut(
            id=inv.id,
            workspace_id=workspace_id,
            workspace_name=workspace.name if workspace else workspace_id,
            inviter_name=inviter.display_name,
            invitee_name=invitee.display_name,
            role=inv.role,
            status=inv.status,
            created_at=inv.created_at,
        )
        for inv, invitee, inviter in workspaces.list_sent_invitations(db, user, workspace_id)
    ]
    return InvitationListOut(invitations=items)


@router.delete("/workspaces/{workspace_id}/invitations/{invitation_id}", status_code=204)
def revoke_invitation(workspace_id: str, invitation_id: str, db: Tx, user: CurrentUser) -> Response:
    try:
        workspaces.revoke_invitation(db, user, workspace_id, invitation_id)
    except members_svc.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)


def invite_link_out(db: Session, link: InviteLink) -> InviteLinkOut:
    """一张邀请链接交给界面的样子(团队页、管理页同一份)。"""
    creator = db.get(User, link.created_by)
    return InviteLinkOut(
        id=link.id,
        code_hint=link.code_hint,
        workspace_id=link.workspace_id,
        role=link.role,
        note=link.note,
        state=members_svc.link_state(link),
        allows_signup=members_svc.link_allows_signup(db, link),
        signup_requested=link.signup_requested_at is not None and not link.signup_approved_by,
        created_by_name=(creator.display_name or creator.username) if creator is not None else "",
        expires_at=link.expires_at,
        created_at=link.created_at,
    )


def issued_out(db: Session, issued: members_svc.IssuedLink) -> IssuedInviteLinkOut:
    """刚发出去的那一张:原文只在这一次;网页地址由部署配(没配就只有深链,ADR 0054 D52)。"""
    return IssuedInviteLinkOut(link=invite_link_out(db, issued.link), code=issued.code, web_url=deployment.web_url(db))


@router.post("/workspaces/{workspace_id}/invite-links", response_model=IssuedInviteLinkOut)
def create_invite_link(workspace_id: str, body: InviteLinkCreate, db: Tx, user: CurrentUser) -> IssuedInviteLinkOut:
    """发一张进这个工作区的邀请链接(ADR 0054):7 天、一次性、能撤回。还没账号的人能不能凭它注册,
    看部署那道门(部署管理员发的自带;否则开放注册,或者请部署管理员放行)。"""
    try:
        return issued_out(db, workspaces.issue_invite_link(db, user, workspace_id, body.role))
    except members_svc.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/workspaces/{workspace_id}/invite-links", response_model=list[InviteLinkOut])
def list_invite_links(workspace_id: str, db: DbSession, user: CurrentUser) -> list[InviteLinkOut]:
    """这个工作区发出去、还能用的链接(和按用户名的邀请列在一起)。"""
    return [invite_link_out(db, link) for link in workspaces.list_invite_links(db, user, workspace_id)]


@router.delete("/workspaces/{workspace_id}/invite-links/{link_id}", status_code=204)
def revoke_invite_link(workspace_id: str, link_id: str, db: Tx, user: CurrentUser) -> Response:
    try:
        workspaces.revoke_invite_link(db, user, workspace_id, link_id)
    except members_svc.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)


@router.post("/workspaces/{workspace_id}/invite-links/{link_id}/request-signup", response_model=InviteLinkOut)
def request_link_signup(workspace_id: str, link_id: str, db: Tx, user: CurrentUser) -> InviteLinkOut:
    """请部署管理员放行:让还没账号的人也能凭这张链接注册(ADR 0054 D48)。"""
    try:
        return invite_link_out(db, workspaces.request_link_signup(db, user, workspace_id, link_id))
    except members_svc.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/invite-links/redeem", response_model=InviteLinkJoinedOut)
def redeem_invite_link(body: InviteCodeIn, db: Tx, user: CurrentUser) -> InviteLinkJoinedOut:
    """已登录的人打开一张工作区邀请链接:直接加入(ADR 0054 D51),界面切过去、说主人和角色、能撤销(退出)。"""
    try:
        joined = members_svc.redeem_invite_link(db, user, body.code)
    except members_svc.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return InviteLinkJoinedOut(
        workspace_id=joined.workspace.id,
        workspace_name=joined.workspace.name,
        role=joined.role,
        owner_name=joined.owner_name,
        already_member=joined.already_member,
    )


@router.get("/invitations", response_model=InvitationListOut)
def my_invitations(db: DbSession, user: CurrentUser) -> InvitationListOut:
    """当前用户的待处理邀请(供通知中心渲染 接受/拒绝)。"""
    items = [
        InvitationOut(
            id=inv.id,
            workspace_id=ws.id,
            workspace_name=ws.name,
            inviter_name=inviter.display_name,
            invitee_name=user.display_name,
            role=inv.role,
            status=inv.status,
            created_at=inv.created_at,
        )
        for inv, ws, inviter in members_svc.pending_invitations(db, user.id)
    ]
    return InvitationListOut(invitations=items)


@router.post("/invitations/{invitation_id}/accept", response_model=InvitationOut)
def accept_invitation(invitation_id: str, db: DbSession, user: CurrentUser) -> InvitationOut:
    return _respond(db, invitation_id, user, accept=True)


@router.post("/invitations/{invitation_id}/decline", response_model=InvitationOut)
def decline_invitation(invitation_id: str, db: DbSession, user: CurrentUser) -> InvitationOut:
    return _respond(db, invitation_id, user, accept=False)


def _respond(db, invitation_id: str, user, *, accept: bool) -> InvitationOut:
    try:
        invitation = members_svc.respond_invitation(db, invitation_id, user, accept)
    except members_svc.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    workspace = db.get(Workspace, invitation.workspace_id)
    inviter = db.get(User, invitation.inviter_id)
    return InvitationOut(
        id=invitation.id,
        workspace_id=invitation.workspace_id,
        workspace_name=workspace.name if workspace else invitation.workspace_id,
        inviter_name=inviter.display_name if inviter else invitation.inviter_id,
        invitee_name=user.display_name,
        role=invitation.role,
        status=invitation.status,
        created_at=invitation.created_at,
    )


@router.patch("/workspaces/{workspace_id}/members/{user_id}", response_model=WorkspaceMemberOut)
def set_member_role(
    workspace_id: str, user_id: str, body: SetRoleRequest, db: Tx, user: CurrentUser
) -> WorkspaceMemberOut:
    try:
        member, member_user = workspaces.change_member_role(db, user, workspace_id, user_id, body.role)
    except members_svc.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return WorkspaceMemberOut(
        user_id=user_id,
        username=member_user.username if member_user else user_id,
        display_name=member_user.display_name if member_user else user_id,
        role=member.role,
    )


@router.delete("/workspaces/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(workspace_id: str, user_id: str, db: Tx, user: CurrentUser) -> Response:
    # 自己退出是任何成员都能做的事;请别人出去要 members 权限。两件事,两道闸。
    try:
        if user_id == user.id:
            workspaces.leave_workspace(db, user, workspace_id)
        else:
            workspaces.remove_other_member(db, user, workspace_id, user_id)
    except members_svc.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(status_code=204)


@router.get("/workspaces/{workspace_id}/summary", response_model=WorkspaceSummaryOut)
def workspace_summary(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    days: int = Query(default=dashboard.WINDOW_DAYS, ge=1, le=dashboard.MAX_WINDOW_DAYS),
) -> WorkspaceSummaryOut:
    # 聚合在 domain/dashboard:它回答的是「这个工作区里发生了什么」,和 HTTP 没关系,而且不止
    # 一个入口要问。**路由的 docstring 会原样进 OpenAPI 的 description**,所以这段写成注释。
    """统计页:工作区一屏统计。只读聚合,单请求给全;任务、发布、花费按 `days` 天的窗口算。"""
    return WorkspaceSummaryOut(**workspaces.summary(db, user, workspace_id, days=days))
