from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    AddMemberRequest,
    MembersOut,
    RenameRequest,
    SetMemberPermsRequest,
    SetRoleRequest,
    WorkspaceMemberOut,
    WorkspaceSummaryOut,
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


@router.get("/workspaces/{workspace_id}/members", response_model=MembersOut)
def list_members(workspace_id: str, db: DbSession, user: CurrentUser) -> MembersOut:
    my_role = workspace_role(db, user, workspace_id)
    if my_role is None:
        raise HTTPException(status_code=404, detail="Not found")
    members = [
        WorkspaceMemberOut(
            user_id=member_user.id,
            username=member_user.username,
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


@router.post("/workspaces/{workspace_id}/members", response_model=WorkspaceMemberOut)
def add_member(workspace_id: str, body: AddMemberRequest, db: DbSession, user: CurrentUser) -> WorkspaceMemberOut:
    ensure_workspace_perm(db, user, workspace_id, "members")
    try:
        member_user, member = members_svc.add_member(db, workspace_id, body.username, body.password, body.role)
    except members_svc.MemberError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return WorkspaceMemberOut(
        user_id=member_user.id,
        username=member_user.username,
        role=member.role,
        perms=effective_member_perms(db, workspace_id, member_user.id, member.role),
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
        role=target.role,
        perms=effective_member_perms(db, workspace_id, user_id, target.role),
    )


@router.get("/workspaces/{workspace_id}/summary", response_model=WorkspaceSummaryOut)
def workspace_summary(workspace_id: str, db: DbSession, user: CurrentUser) -> WorkspaceSummaryOut:
    """首页仪表:工作区一屏统计。只读聚合,单请求给全。"""
    from datetime import timedelta

    from sqlalchemy import func

    from app.db.models import now

    ensure_workspace_access(db, user, workspace_id)

    def count(stmt) -> int:
        return int(db.scalar(stmt) or 0)

    week_ago = now() - timedelta(days=7)
    scoped = lambda model: select(func.count()).select_from(model).where(model.workspace_id == workspace_id)  # noqa: E731

    return WorkspaceSummaryOut(
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
