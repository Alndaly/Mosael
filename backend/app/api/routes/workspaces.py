from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response
from pydantic import BaseModel

from app.core.i18n import tr
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    InviteMemberRequest,
    MembersOut,
    RenameRequest,
    SetRoleRequest,
    WorkspaceMemberOut,
    WorkspaceSummaryOut,
    InvitationOut,
    InvitationListOut,
)
from app.domain.permissions import PermissionDenied, ensure_workspace_access, ensure_workspace_perm, ensure_workspace_role, workspace_role
from app.db.models import (
    User,
    Workspace,
    WorkspaceMember,
)
from app.domain import dashboard, members as members_svc

router = APIRouter(tags=["workspaces"])

@router.patch("/workspaces/{workspace_id}")
def rename_workspace(workspace_id: str, body: RenameRequest, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_role(db, user, workspace_id, "admin")
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Not found")
    workspace.name = body.name
    db.commit()
    return {"id": workspace.id, "name": workspace.name}


class AutopilotRulesBody(BaseModel):
    rules: dict = {}


@router.get("/workspaces/{workspace_id}/autopilot-rules")
def get_autopilot_rules(workspace_id: str, db: DbSession, user: CurrentUser) -> dict:
    """auto 档下 `external` 的放行准则(见 domain/agent/rules)。读:工作区成员即可。"""
    from app.domain.agent import rules as autopilot_rules

    ensure_workspace_access(db, user, workspace_id)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Not found")
    return {"rules": autopilot_rules.normalize(workspace.autopilot_rules)}


@router.put("/workspaces/{workspace_id}/autopilot-rules")
def set_autopilot_rules(
    workspace_id: str, body: AutopilotRulesBody, db: DbSession, user: CurrentUser
) -> dict:
    """改准则要 admin。

    它决定的是「什么可以不问就发出去」—— 往主机白名单里加一行,等于让智能体从此可以不经确认
    对那个地址发写请求。这和开 bypass 是同一级别的授权动作,不该是每个编辑都能改的。
    """
    from app.domain.agent import rules as autopilot_rules

    ensure_workspace_role(db, user, workspace_id, "admin")
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Not found")
    incoming = autopilot_rules.normalize(body.rules)
    # 名单类的东西属于这个工作区(发布账号、浏览器档案本来就挂在它上面),工作区管理员说了算。
    # **但「在这台机器上跑代码」不是** —— 它和工作流里的 code 节点是同一个能力,所以走同一道闸
    # (ensure_deployment_admin)。同一个能力两个门槛的话,低的那个说了算,而承担风险的是机器的主人。
    #
    # 那道闸今天有多高要说清楚:`ensure_deployment_admin` 的实际语义是「在**任意**一个工作区里是
    # owner/admin」,不是「这台机器的主人」—— 它拦得住 editor,拦不住别处的管理员。这不是这条准则
    # 的问题,是整套作用域模型里缺一层(见 docs/ADR 待议)。共用同一道闸的意义正在于此:那天它收紧,
    # 这里跟着一起收紧,不需要有人记得回来改第二处。
    current = autopilot_rules.normalize(workspace.autopilot_rules)
    if any(incoming[key] == "judge" and current[key] != "judge" for key in ("run_code", "run_host_code")):
        try:
            ensure_workspace_role(db, user, workspace_id, "admin")
        except PermissionDenied as exc:
            raise HTTPException(
                status_code=403,
                detail=tr("routeErr_judgeHostCodeNeedsAdmin"),
            ) from exc
    workspace.autopilot_rules = incoming
    db.commit()
    return {"rules": workspace.autopilot_rules}


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, db: DbSession, user: CurrentUser) -> Response:
    ensure_workspace_role(db, user, workspace_id, "owner")
    workspace = db.get(Workspace, workspace_id)
    if workspace is not None:
        db.delete(workspace)  # FK cascade removes members and all scoped resources
        db.commit()
        # 行是 CASCADE 走的,**文件不会** —— 3D 模型归工作区(见 domain/scenes),和字体、
        # LUT 同一套,由删除那条路显式清掉。
        from app.domain.scenes import delete_workspace_model_files

        delete_workspace_model_files(workspace_id)
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
    my_role = workspace_role(db, user, workspace_id)
    if my_role is None:
        raise HTTPException(status_code=404, detail="Not found")
    members = [
        WorkspaceMemberOut(
            user_id=member_user.id,
            username=member_user.username,
            display_name=member_user.display_name,
            role=member.role,
            is_self=member_user.id == user.id,
        )
        for member_user, member in members_svc.list_members(db, workspace_id)
    ]
    return MembersOut(
        members=members,
        my_role=my_role,
    )


@router.post("/workspaces/{workspace_id}/invitations", response_model=InvitationOut)
def invite_member(workspace_id: str, body: InviteMemberRequest, db: DbSession, user: CurrentUser) -> InvitationOut:
    """邀请制:只对已注册用户名发邀请,对方在通知里接受后才建成员行。"""
    ensure_workspace_perm(db, user, workspace_id, "members")
    try:
        invitee, invitation = members_svc.invite_member(db, workspace_id, user, body.username, body.role)
    except members_svc.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    workspace = db.get(Workspace, workspace_id)
    return InvitationOut(
        id=invitation.id,
        workspace_id=workspace_id,
        workspace_name=workspace.name if workspace else workspace_id,
        inviter_name=user.display_name,
        invitee_name=invitee.display_name,
        role=invitation.role,
        status=invitation.status,
        created_at=invitation.created_at,
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
    workspace_id: str, user_id: str, body: SetRoleRequest, db: DbSession, user: CurrentUser
) -> WorkspaceMemberOut:
    caller_role = ensure_workspace_role(db, user, workspace_id, "admin")
    ensure_workspace_perm(db, user, workspace_id, "members")
    target = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id})
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")
    # Only an owner may grant or modify the owner role (prevents admins minting owners / self-promoting).
    if (body.role == "owner" or target.role == "owner") and caller_role != "owner":
        raise HTTPException(status_code=403, detail="Only an owner can change owner role")
    try:
        member = members_svc.set_role(db, workspace_id, user_id, body.role)
    except members_svc.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    member_user = db.get(User, user_id)
    return WorkspaceMemberOut(
        user_id=user_id,
        username=member_user.username if member_user else user_id,
        display_name=member_user.display_name if member_user else user_id,
        role=member.role,
    )


@router.delete("/workspaces/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(workspace_id: str, user_id: str, db: DbSession, user: CurrentUser) -> Response:
    # Self-leave is allowed for any member; removing someone else needs the members perm.
    if user_id != user.id:
        ensure_workspace_perm(db, user, workspace_id, "members")
        caller_role = workspace_role(db, user, workspace_id)
        target = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id})
        if target is not None and target.role == "owner" and caller_role != "owner":
            raise HTTPException(status_code=403, detail="Only an owner can remove an owner")
    else:
        ensure_workspace_access(db, user, workspace_id)
    try:
        members_svc.remove_member(db, workspace_id, user_id)
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
    ensure_workspace_access(db, user, workspace_id)
    return WorkspaceSummaryOut(**dashboard.workspace_summary(db, workspace_id, days=days))
