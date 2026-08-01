from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    InviteMemberRequest,
    DailyActivityOut,
    DailyPublishOut,
    MembersOut,
    RenameRequest,
    SetMemberPermsRequest,
    SetRoleRequest,
    WorkspaceMemberOut,
    WorkspaceSummaryOut,
    InvitationOut,
    InvitationListOut,
)
from app.core.permissions import (
    effective_member_perms,
    ensure_workspace_access,
    ensure_workspace_perm,
    ensure_workspace_role,
    workspace_role,
)
from app.core.roles import PERMS, ROLES, role_defaults
from app.db.models import (
    Asset,
    Job,
    KbDocument,
    Project,
    PublishAccount,
    PublishTask,
    Sequence,
    User,
    Workflow,
    Workspace,
    WorkspaceMember,
)
from app.domain import members as members_svc

router = APIRouter(tags=["workspaces"])

PUBLISH_ACTIVE_STATUSES = frozenset({"pending", "queued", "running", "prepared"})
PUBLISH_BLOCKED_STATUSES = frozenset({"login_required", "waiting_manual", "permission_required", "blocked"})


def _publish_summary_bucket(status: str) -> str:
    if status == "success":
        return "succeeded"
    if status in ("failed", "cancelled"):
        return "failed"
    if status in PUBLISH_BLOCKED_STATUSES:
        return "blocked"
    if status in PUBLISH_ACTIVE_STATUSES:
        return "active"
    return "active"


@router.patch("/workspaces/{workspace_id}")
def rename_workspace(workspace_id: str, body: RenameRequest, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_role(db, user, workspace_id, "admin")
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status_code=404, detail="Not found")
    workspace.name = body.name
    db.commit()
    return {"id": workspace.id, "name": workspace.name}


@router.delete("/workspaces/{workspace_id}", status_code=204)
def delete_workspace(workspace_id: str, db: DbSession, user: CurrentUser) -> Response:
    ensure_workspace_role(db, user, workspace_id, "owner")
    workspace = db.get(Workspace, workspace_id)
    if workspace is not None:
        db.delete(workspace)  # FK cascade removes members, perms, and all scoped resources
        db.commit()
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
        raise HTTPException(status_code=502, detail=f"今日诗词暂时不可达:{exc}") from exc
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
            perms=effective_member_perms(db, workspace_id, member_user.id, member.role),
            is_self=member_user.id == user.id,
        )
        for member_user, member in members_svc.list_members(db, workspace_id)
    ]
    return MembersOut(
        members=members,
        my_role=my_role,
        perm_keys=list(PERMS),
        role_defaults={role: role_defaults(role) for role in ROLES},
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
        perms=effective_member_perms(db, workspace_id, user_id, member.role),
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


@router.patch("/workspaces/{workspace_id}/members/{user_id}/perms", response_model=WorkspaceMemberOut)
def set_member_perms(
    workspace_id: str, user_id: str, body: SetMemberPermsRequest, db: DbSession, user: CurrentUser
) -> WorkspaceMemberOut:
    ensure_workspace_perm(db, user, workspace_id, "members")
    target = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id})
    if target is None:
        raise HTTPException(status_code=404, detail="Not found")
    try:
        members_svc.set_perms(db, workspace_id, user_id, body.perms)
    except members_svc.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    member_user = db.get(User, user_id)
    return WorkspaceMemberOut(
        user_id=user_id,
        username=member_user.username if member_user else user_id,
        display_name=member_user.display_name if member_user else user_id,
        role=target.role,
        perms=effective_member_perms(db, workspace_id, user_id, target.role),
    )


@router.get("/workspaces/{workspace_id}/summary", response_model=WorkspaceSummaryOut)
def workspace_summary(workspace_id: str, db: DbSession, user: CurrentUser) -> WorkspaceSummaryOut:
    """首页仪表:工作区一屏统计。只读聚合,单请求给全。"""
    from datetime import datetime, timedelta

    from sqlalchemy import func

    from app.db.models import now
    from app.domain.usage import summarize_usage

    ensure_workspace_access(db, user, workspace_id)

    def count(stmt) -> int:
        return int(db.scalar(stmt) or 0)

    week_ago = now() - timedelta(days=7)
    scoped = lambda model: select(func.count()).select_from(model).where(model.workspace_id == workspace_id)  # noqa: E731

    # 活动图:近 14 天逐日成功/失败(按终态时间 updated_at 归日,UTC),缺日补零。
    span_start = (now() - timedelta(days=13)).date()
    day_rows = db.execute(
        select(func.date(Job.updated_at), Job.status, func.count())
        .where(
            Job.workspace_id == workspace_id,
            Job.status.in_(("succeeded", "failed")),
            Job.updated_at >= datetime.combine(span_start, datetime.min.time()),
        )
        .group_by(func.date(Job.updated_at), Job.status)
    ).all()
    by_day: dict[str, dict[str, int]] = {}
    for day, status, count_ in day_rows:
        by_day.setdefault(str(day), {})[str(status)] = int(count_)
    daily = [
        DailyActivityOut(
            date=str(span_start + timedelta(days=offset)),
            succeeded=by_day.get(str(span_start + timedelta(days=offset)), {}).get("succeeded", 0),
            failed=by_day.get(str(span_start + timedelta(days=offset)), {}).get("failed", 0),
        )
        for offset in range(14)
    ]

    publish_day_rows = db.execute(
        select(func.date(PublishTask.updated_at), PublishTask.status, func.count())
        .where(
            PublishTask.workspace_id == workspace_id,
            PublishTask.updated_at >= datetime.combine(span_start, datetime.min.time()),
        )
        .group_by(func.date(PublishTask.updated_at), PublishTask.status)
    ).all()
    publish_by_day: dict[str, dict[str, int]] = {}
    for day, status, count_ in publish_day_rows:
        bucket = _publish_summary_bucket(str(status))
        publish_by_day.setdefault(str(day), {}).setdefault(bucket, 0)
        publish_by_day[str(day)][bucket] += int(count_)
    publish_daily = [
        DailyPublishOut(
            date=str(span_start + timedelta(days=offset)),
            succeeded=publish_by_day.get(str(span_start + timedelta(days=offset)), {}).get("succeeded", 0),
            failed=publish_by_day.get(str(span_start + timedelta(days=offset)), {}).get("failed", 0),
            active=publish_by_day.get(str(span_start + timedelta(days=offset)), {}).get("active", 0),
            blocked=publish_by_day.get(str(span_start + timedelta(days=offset)), {}).get("blocked", 0),
        )
        for offset in range(14)
    ]

    kind_rows = db.execute(
        select(Asset.kind, func.count()).where(Asset.workspace_id == workspace_id).group_by(Asset.kind)
    ).all()
    asset_kinds = {str(kind): int(count_) for kind, count_ in kind_rows}
    publish_platform_rows = db.execute(
        select(PublishAccount.platform, func.count())
        .select_from(PublishTask)
        .join(PublishAccount, PublishAccount.id == PublishTask.account_id)
        .where(PublishTask.workspace_id == workspace_id)
        .group_by(PublishAccount.platform)
    ).all()
    publish_platforms = {str(platform): int(count_) for platform, count_ in publish_platform_rows}
    usage = summarize_usage(db, workspace_id=workspace_id, days=14)

    return WorkspaceSummaryOut(
        daily=daily,
        asset_kinds=asset_kinds,
        publish_daily=publish_daily,
        publish_platforms=publish_platforms,
        usage_cost_micros=usage.total_cost_micros,
        usage_currency=usage.currency,
        usage_event_count=usage.event_count,
        usage_unknown_cost_events=usage.unknown_cost_events,
        usage_duration_seconds=usage.duration_seconds,
        usage_token_count=usage.token_count,
        usage_cache_read_tokens=usage.cache_read_tokens,
        usage_cache_write_tokens=usage.cache_write_tokens,
        usage_cache_hit_ratio=usage.cache_hit_ratio,
        usage_daily=usage.daily,
        usage_token_daily=usage.token_daily,
        usage_by_capability=usage.by_capability,
        usage_by_provider=usage.by_provider,
        project_count=count(scoped(Project)),
        asset_count=count(scoped(Asset)),
        sequence_count=count(scoped(Sequence)),
        workflow_count=count(scoped(Workflow)),
        kb_document_count=count(scoped(KbDocument)),
        running_jobs=count(scoped(Job).where(Job.status.in_(("queued", "running")))),
        week_jobs_succeeded=count(scoped(Job).where(Job.status == "succeeded", Job.updated_at >= week_ago)),
        week_jobs_failed=count(scoped(Job).where(Job.status == "failed", Job.updated_at >= week_ago)),
        publish_accounts=count(scoped(PublishAccount)),
        week_published=count(
            scoped(PublishTask).where(PublishTask.status == "success", PublishTask.updated_at >= week_ago)
        ),
    )
