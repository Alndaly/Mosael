"""工作区与成员管理的用例:谁能做、做什么写在一起(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

改名、改放行准则要 admin;删工作区要 owner;邀请、改角色、请人出去点名 `members`;
自己退出只要是成员。不是成员的,工作区对他不存在(404)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import User, Workspace, WorkspaceInvitation, WorkspaceMember
from app.domain import dashboard
from app.domain import members as members_svc
from app.domain.agent import rules as autopilot_rules
from app.domain.permissions import (
    NotVisible,
    PermissionDenied,
    ensure_deployment_admin,
    ensure_workspace_access,
    ensure_workspace_perm,
    ensure_workspace_role,
    workspace_role,
)


def _workspace(db: Session, workspace_id: str) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise NotVisible("Not found")
    return workspace


# ---------------- 工作区 ----------------


def create_workspace(db: Session, user: User, name: str) -> Workspace:
    """建的人成为它的 owner —— 还没有工作区可查,不过闸。"""
    return members_svc.create_workspace(db, name, user)


def rename_workspace(db: Session, user: User, workspace_id: str, name: str) -> Workspace:
    ensure_workspace_role(db, user, workspace_id, "admin")
    workspace = _workspace(db, workspace_id)
    workspace.name = name
    return workspace


def delete_workspace(db: Session, user: User, workspace_id: str) -> None:
    ensure_workspace_role(db, user, workspace_id, "owner")
    members_svc.delete_workspace(db, workspace_id)


def autopilot_rules_of(db: Session, user: User, workspace_id: str) -> dict[str, Any]:
    """auto 档下 `external` 的放行准则(见 agent/rules)。读:工作区成员即可。"""
    ensure_workspace_access(db, user, workspace_id)
    return autopilot_rules.normalize(_workspace(db, workspace_id).autopilot_rules)


def set_autopilot_rules(db: Session, user: User, workspace_id: str, rules: dict[str, Any]) -> dict[str, Any]:
    """改准则要 admin:它决定的是「什么可以不问就发出去」,和开 bypass 是同一级别的授权动作。"""
    ensure_workspace_role(db, user, workspace_id, "admin")
    workspace = _workspace(db, workspace_id)
    incoming = autopilot_rules.normalize(rules)
    # 名单类的东西属于这个工作区(发布账号、浏览器档案本来就挂在它上面),工作区管理员说了算。
    # 沙箱里跑的 run_code 也是(ADR 0008 D2:代码跑在内核强制的隔离里,写它就是普通的内容编辑)。
    # **但「在这台电脑上不隔离地跑代码」(run_host_code)不是** —— 它能读写后端能读写的一切,
    # 承担风险的是机器的主人,和「本机文件归部署主人」同一条(domain/host_files)。所以不再逐次
    # 问人(交给判断者,或者 always 直接放行),要这个部署的管理员点头。
    #
    # 此前这里调的是上面已经过了的同一个 ensure_workspace_role(..., "admin"),这道闸等于不存在;
    # 而且只拦 judge,比它更宽的 always 从旁边就过去了。
    current = autopilot_rules.normalize(workspace.autopilot_rules)
    loosened = incoming["run_host_code"] != "ask" and incoming["run_host_code"] != current["run_host_code"]
    if loosened:
        try:
            ensure_deployment_admin(db, user)
        except PermissionDenied as exc:
            raise PermissionDenied("routeErr_judgeHostCodeNeedsAdmin") from exc
    workspace.autopilot_rules = incoming
    return workspace.autopilot_rules


def summary(db: Session, user: User, workspace_id: str, *, days: int) -> dict[str, Any]:
    """统计页的一屏统计(聚合在 domain/dashboard)。"""
    ensure_workspace_access(db, user, workspace_id)
    return dashboard.workspace_summary(db, workspace_id, days=days)


# ---------------- 成员 ----------------


def members_of(db: Session, user: User, workspace_id: str) -> tuple[str, list[tuple[User, WorkspaceMember]]]:
    """(他在这里的角色, 全部成员)。"""
    my_role = workspace_role(db, user, workspace_id)
    if my_role is None:
        raise NotVisible("Not found")
    return my_role, members_svc.list_members(db, workspace_id)


def invite_to_workspace(
    db: Session, user: User, workspace_id: str, username: str, role: str
) -> tuple[User, WorkspaceInvitation, str]:
    """邀请制:只对已注册用户名发邀请,对方在通知里接受后才建成员行。回 (受邀人, 邀请, 工作区名)。"""
    ensure_workspace_perm(db, user, workspace_id, "members")
    invitee, invitation = members_svc.invite_member(db, workspace_id, user, username, role)
    workspace = db.get(Workspace, workspace_id)
    return invitee, invitation, workspace.name if workspace else workspace_id


def list_sent_invitations(db: Session, user: User, workspace_id: str) -> list[tuple[WorkspaceInvitation, User, User]]:
    """发出去、还没应答的邀请。和发邀请同一道闸(`members`)。"""
    ensure_workspace_perm(db, user, workspace_id, "members")
    return members_svc.sent_invitations(db, workspace_id)


def revoke_invitation(db: Session, user: User, workspace_id: str, invitation_id: str) -> None:
    ensure_workspace_perm(db, user, workspace_id, "members")
    members_svc.revoke_invitation(db, workspace_id, invitation_id)


def change_member_role(
    db: Session, user: User, workspace_id: str, user_id: str, role: str
) -> tuple[WorkspaceMember, User | None]:
    caller_role = ensure_workspace_role(db, user, workspace_id, "admin")
    ensure_workspace_perm(db, user, workspace_id, "members")
    if db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id}) is None:
        raise NotVisible("Not found")
    members_svc.ensure_may_touch_owner(db, workspace_id, user_id, actor_role=caller_role, new_role=role)
    member = members_svc.set_role(db, workspace_id, user_id, role)
    return member, db.get(User, user_id)


def remove_other_member(db: Session, user: User, workspace_id: str, user_id: str) -> None:
    """请别人出去要 `members`;所有者只有所有者能请(见 members.ensure_may_touch_owner)。"""
    ensure_workspace_perm(db, user, workspace_id, "members")
    members_svc.ensure_may_touch_owner(db, workspace_id, user_id, actor_role=workspace_role(db, user, workspace_id))
    members_svc.remove_member(db, workspace_id, user_id)


def leave_workspace(db: Session, user: User, workspace_id: str) -> None:
    """自己退出:是成员就行。最后一个 owner 不能走(members.remove_member 报)。"""
    ensure_workspace_access(db, user, workspace_id)
    members_svc.remove_member(db, workspace_id, user.id)
