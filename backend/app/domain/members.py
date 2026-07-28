"""Workspace membership operations with the "last owner" invariant.

A workspace must always keep at least one owner — you can't demote or remove the last
one, or the workspace becomes unmanageable. That check-then-write must be atomic, so the
mutating ops run under a module lock (mirrors the predecessor project's core/workspaces.py RLock).
Actor-level authorization (who may call these) is enforced in the route layer.
"""
from __future__ import annotations

import threading

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.roles import PERMS
from app.db.models import User, Workspace, WorkspaceInvitation, WorkspaceMember, WorkspaceMemberPerm
from app.domain import notifications as notifications_svc

_lock = threading.RLock()


class MemberError(Exception):
    """Domain error → mapped to HTTP 400/409 by the route."""


def owners_count(db: Session, workspace_id: str) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner")
        )
        or 0
    )


def list_members(db: Session, workspace_id: str) -> list[tuple[User, WorkspaceMember]]:
    rows = db.execute(
        select(User, WorkspaceMember)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.created_at.asc())
    ).all()
    return [(user, member) for user, member in rows]


def invite_member(db: Session, workspace_id: str, inviter: User, username: str, role: str) -> tuple[User, WorkspaceInvitation]:
    """邀请制入口:按用户名邀请一个**已注册**账号,受邀人从通知里接受后才成为成员。

    不再替队友建号(旧 add_member 已删):账号自助注册,管理员只发邀请——
    密码从此不经过任何第三人之手。"""
    username = username.strip().lower()
    with _lock:
        invitee = db.scalar(select(User).where(User.username == username))
        if invitee is None:
            raise MemberError("该用户名不存在;请对方先在登录页注册账号")
        if invitee.id == inviter.id:
            raise MemberError("不能邀请自己")
        if db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": invitee.id}) is not None:
            raise MemberError("对方已是本工作区成员")
        pending = db.scalar(
            select(WorkspaceInvitation).where(
                WorkspaceInvitation.workspace_id == workspace_id,
                WorkspaceInvitation.invitee_id == invitee.id,
                WorkspaceInvitation.status == "pending",
            )
        )
        if pending is not None:
            raise MemberError("已有待处理的邀请")
        invitation = WorkspaceInvitation(
            workspace_id=workspace_id, inviter_id=inviter.id, invitee_id=invitee.id, role=role
        )
        db.add(invitation)
        db.flush()
        workspace = db.get(Workspace, workspace_id)
        notifications_svc.notify(
            db,
            workspace_id,
            type="team",
            title=f"{inviter.display_name} 邀请你加入「{workspace.name if workspace else workspace_id}」",
            body=f"角色:{role}。接受后即可访问该工作区。",
            payload={"kind": "invite", "invitation_id": invitation.id, "role": role},
            user_id=invitee.id,
        )
        db.commit()
        db.refresh(invitation)
    return invitee, invitation


def pending_invitations(db: Session, user_id: str) -> list[tuple[WorkspaceInvitation, Workspace, User]]:
    """当前用户的待处理邀请(通知中心据此渲染 接受/拒绝)。"""
    rows = db.execute(
        select(WorkspaceInvitation, Workspace, User)
        .join(Workspace, Workspace.id == WorkspaceInvitation.workspace_id)
        .join(User, User.id == WorkspaceInvitation.inviter_id)
        .where(WorkspaceInvitation.invitee_id == user_id, WorkspaceInvitation.status == "pending")
        .order_by(WorkspaceInvitation.created_at.desc())
    ).all()
    return [(inv, ws, inviter) for inv, ws, inviter in rows]


def respond_invitation(db: Session, invitation_id: str, user: User, accept: bool) -> WorkspaceInvitation:
    """受邀人应答。接受 → 建成员行(成员行仍只在本域创建);拒绝 → 仅记状态。
    双向留痕:结果同样通知邀请人。"""
    from app.db.models import now as _now

    with _lock:
        invitation = db.get(WorkspaceInvitation, invitation_id)
        if invitation is None or invitation.invitee_id != user.id:
            raise MemberError("邀请不存在")
        if invitation.status != "pending":
            raise MemberError("邀请已处理过")
        invitation.status = "accepted" if accept else "declined"
        invitation.responded_at = _now()
        if accept and db.get(WorkspaceMember, {"workspace_id": invitation.workspace_id, "user_id": user.id}) is None:
            db.add(WorkspaceMember(workspace_id=invitation.workspace_id, user_id=user.id, role=invitation.role))
        workspace = db.get(Workspace, invitation.workspace_id)
        ws_name = workspace.name if workspace else invitation.workspace_id
        notifications_svc.notify(
            db,
            invitation.workspace_id,
            type="team",
            title=f"{user.display_name} {'接受' if accept else '婉拒'}了加入「{ws_name}」的邀请",
            body="",
            payload={"kind": "invite-result", "invitation_id": invitation.id, "accepted": accept},
            user_id=invitation.inviter_id,
        )
        db.commit()
        db.refresh(invitation)
    return invitation


def set_role(db: Session, workspace_id: str, user_id: str, role: str) -> WorkspaceMember:
    with _lock:
        member = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id})
        if member is None:
            raise MemberError("Not a member")
        if member.role == "owner" and role != "owner" and owners_count(db, workspace_id) <= 1:
            raise MemberError("Cannot demote the last owner")
        member.role = role
        if role == "owner":
            _clear_overrides(db, workspace_id, user_id)  # owner ignores overrides; drop stale rows
        db.commit()
        db.refresh(member)
    return member


def remove_member(db: Session, workspace_id: str, user_id: str) -> None:
    with _lock:
        member = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id})
        if member is None:
            raise MemberError("Not a member")
        if member.role == "owner" and owners_count(db, workspace_id) <= 1:
            raise MemberError("Cannot remove the last owner")
        _clear_overrides(db, workspace_id, user_id)
        db.delete(member)
        db.commit()


def set_perms(db: Session, workspace_id: str, user_id: str, overrides: dict[str, bool]) -> None:
    """Replace this member's per-perm overrides with `overrides` (only keys that differ
    from the role default need to be stored, but we accept any and prune no-ops)."""
    member = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id})
    if member is None:
        raise MemberError("Not a member")
    if member.role == "owner":
        raise MemberError("Owner always has every permission")
    _clear_overrides(db, workspace_id, user_id)
    for perm, allowed in overrides.items():
        if perm in PERMS:
            db.add(WorkspaceMemberPerm(workspace_id=workspace_id, user_id=user_id, perm=perm, allowed=bool(allowed)))
    db.commit()


def _clear_overrides(db: Session, workspace_id: str, user_id: str) -> None:
    for row in db.scalars(
        select(WorkspaceMemberPerm).where(
            WorkspaceMemberPerm.workspace_id == workspace_id,
            WorkspaceMemberPerm.user_id == user_id,
        )
    ):
        db.delete(row)
