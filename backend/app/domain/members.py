"""账号与工作区成员:谁能进这个部署、谁在哪个工作区里。

Workspace membership operations with the "last owner" invariant.

A workspace must always keep at least one owner — you can't demote or remove the last
one, or the workspace becomes unmanageable. That check-then-write must be atomic, so the
mutating ops run under a module lock (mirrors the predecessor project's core/workspaces.py RLock).
Actor-level authorization (who may call these) is enforced in the route layer.
"""
from __future__ import annotations

import secrets
import threading

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError, tr
from app.core.security import hash_password
from app.db.models import RegistrationInvite, User, Workspace, WorkspaceInvitation, WorkspaceMember, now
from app.domain import deployment
from app.domain import notifications as notifications_svc

_lock = threading.RLock()


class MemberError(LocalizedError):
    """Domain error → mapped to HTTP 400/409 by the route. 带文案 key(`memberErr_*`)。"""


class SignupClosed(MemberError):
    """这个部署不收自助注册,也没带一个还能用的邀请码。"""


class UsernameTaken(MemberError):
    """用户名已经有人用了。"""


def normalize_username(value: str) -> str:
    return value.strip().lower()


def usable_invite(db: Session, code: str) -> RegistrationInvite | None:
    """还能用的注册邀请码:存在、没用过、没过期。看不懂的码一律当作没有。"""
    code = (code or "").strip()
    if not code:
        return None
    invite = db.get(RegistrationInvite, code)
    if invite is None or invite.used_by or invite.expires_at <= now():
        return None
    return invite


def create_account(db: Session, *, username: str, display_name: str, password: str | None, invite_code: str = "") -> User:
    """建一个账号。本地注册和第三方登录第一次进来**都走这里**。

    此前两处各建各的,而第三方登录那处不看注册闸门:部署关掉自助注册之后,只要配了 Google /
    Apple 登录,任何人照样能进来 —— 正是 ADR 0008 §0 那条提权链的第一环。

    **引导之后转邀请制**:空库时照常放行 —— 那时没有任何人能发邀请,而没有部署管理员的部署是块
    砖头,所以第一个账号成为部署管理员,并认领登录之前建的工作区。之后要么部署开放注册,要么带
    一个还能用的邀请码(一次性:用掉就作废)。

    `password` 为 None 是第三方账号:没有本地口令,填一个不可用的随机散列,密码登录天然走不通。
    flush 拿到 id,提交交给调用方 —— 会话行要和账号一起进库。
    """
    bootstrapping = db.scalar(select(User).limit(1)) is None
    invite = usable_invite(db, invite_code)
    if not bootstrapping and invite is None and not deployment.open_registration(db):
        raise SignupClosed("routeErr_signupClosed")
    username = normalize_username(username)
    if db.scalar(select(User).where(User.username == username)) is not None:
        raise UsernameTaken("memberErr_usernameTaken")
    user = User(
        username=username,
        display_name=display_name.strip() or username,
        signature="",
        password_hash=hash_password(password if password is not None else secrets.token_hex(24)),
        is_deployment_admin=bootstrapping,
    )
    db.add(user)
    db.flush()
    _adopt_orphan_workspaces(db, user)
    if invite is not None:
        invite.used_by = user.id
    return user


def free_username(db: Session, base: str) -> str:
    """`base` 没人用就是它,否则依次试 base2、base3……(第三方登录拿邮箱局部名起名时用)。"""
    username = normalize_username(base)
    suffix = 1
    while db.scalar(select(User).where(User.username == username)) is not None:
        suffix += 1
        username = f"{normalize_username(base)}{suffix}"
    return username


def _adopt_orphan_workspaces(db: Session, user: User) -> None:
    """本机升级路径:库里还没有任何成员关系时,第一个账号继承登录之前建的那些工作区。"""
    if db.scalar(select(WorkspaceMember).limit(1)) is not None:
        return
    for workspace in db.scalars(select(Workspace)):
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))


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


def create_workspace(db: Session, name: str, owner: User) -> Workspace:
    """建一个工作区,建的人是它的 owner —— 「至少一个 owner」从第一刻起就成立。
    flush 拿到 id,提交交给调用方。"""
    workspace = Workspace(name=name)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner"))
    return workspace


def workspaces_of(db: Session, user_id: str) -> list[tuple[Workspace, str]]:
    """他所在的工作区和他在里面的角色,新建的在前。"""
    rows = db.execute(
        select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user_id)
        .order_by(Workspace.created_at.desc())
    ).all()
    return [(workspace, role) for workspace, role in rows]


def invite_member(db: Session, workspace_id: str, inviter: User, username: str, role: str) -> tuple[User, WorkspaceInvitation]:
    """邀请制入口:按用户名邀请一个**已注册**账号,受邀人从通知里接受后才成为成员。

    不再替队友建号(旧 add_member 已删):账号自助注册,管理员只发邀请——
    密码从此不经过任何第三人之手。"""
    username = username.strip().lower()
    with _lock:
        invitee = db.scalar(select(User).where(User.username == username))
        if invitee is None:
            raise MemberError("memberErr_userNotFound")
        if invitee.id == inviter.id:
            raise MemberError("memberErr_inviteSelf")
        if db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": invitee.id}) is not None:
            raise MemberError("memberErr_alreadyMember")
        pending = db.scalar(
            select(WorkspaceInvitation).where(
                WorkspaceInvitation.workspace_id == workspace_id,
                WorkspaceInvitation.invitee_id == invitee.id,
                WorkspaceInvitation.status == "pending",
            )
        )
        if pending is not None:
            raise MemberError("memberErr_invitePending")
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
            raise MemberError("memberErr_inviteNotFound")
        if invitation.status != "pending":
            raise MemberError("memberErr_inviteHandled")
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
            raise MemberError("memberErr_notMember")
        if member.role == "owner" and role != "owner" and owners_count(db, workspace_id) <= 1:
            raise MemberError("memberErr_lastOwnerDemote")
        member.role = role
        db.commit()
        db.refresh(member)
    return member


def remove_member(db: Session, workspace_id: str, user_id: str) -> None:
    with _lock:
        member = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id})
        if member is None:
            raise MemberError("memberErr_notMember")
        if member.role == "owner" and owners_count(db, workspace_id) <= 1:
            raise MemberError("memberErr_lastOwnerRemove")
        db.delete(member)
        db.commit()





#: 指向"某个人"的列。删账号时要跟着走的就是这些 —— **按 schema 认,不手写清单**:
#: 新加一张带 owner_user_id 的表时,手写清单不会有任何东西提醒你漏了它,而漏掉的那些行会
#: 变成指向不存在的人的孤儿(这些列有意不设外键,见 db.models)。
PERSON_COLUMNS = ("user_id", "owner_user_id")


def _tables_pointing_at_a_person() -> list[tuple[str, str]]:
    from app.db.models import Base

    return [
        (table.name, column.name)
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if column.name in PERSON_COLUMNS
    ]


def solo_workspaces(db: Session, user_id: str) -> list[Workspace]:
    """只有他一个成员的工作区。"""
    rows = db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user_id)).all()
    out: list[Workspace] = []
    for member in rows:
        others = db.scalar(
            select(func.count())
            .select_from(WorkspaceMember)
            .where(WorkspaceMember.workspace_id == member.workspace_id, WorkspaceMember.user_id != user_id)
        )
        if not others:
            workspace = db.get(Workspace, member.workspace_id)
            if workspace is not None:
                out.append(workspace)
    return out


def shared_workspaces(db: Session, user_id: str) -> list[Workspace]:
    """他在里面、但还有别人的工作区。删账号时这些**不跟着走**。"""
    solo = {w.id for w in solo_workspaces(db, user_id)}
    rows = db.scalars(select(WorkspaceMember).where(WorkspaceMember.user_id == user_id)).all()
    return [w for w in (db.get(Workspace, m.workspace_id) for m in rows) if w is not None and w.id not in solo]


def delete_account(db: Session, user: User) -> None:
    """删掉这个账号,以及只属于他的那些东西。

    **他独占的工作区跟着他走**(里面只有他自己的内容,留着就是一堆没人看得见的行);**还有别人
    在的不跟着走** —— 那里面有同事的素材、时间线、对话,宁可让管理员先去转让,也不要一次点击
    毁掉别人的工作。

    删的范围按 schema 推导(见 PERSON_COLUMNS),不手写清单:`agent_sessions.owner_user_id`
    这类列有意不设外键,手写清单漏掉一张表不会有任何东西报错,只会留下指向不存在的人的孤儿行。

    和「不能收回最后一个部署管理员」同一条:最后一个管理员不能删,否则这台部署没人管了。
    """
    with _lock:
        if user.is_deployment_admin:
            others = db.scalar(
                select(func.count()).select_from(User).where(User.is_deployment_admin.is_(True), User.id != user.id)
            )
            if not others:
                raise MemberError("memberErr_lastDeploymentAdmin")
        blocked = shared_workspaces(db, user.id)
        if blocked:
            names = tr("punct_listSep").join(w.name for w in blocked)
            raise MemberError("memberErr_sharedWorkspaces", names=names)

        for workspace in solo_workspaces(db, user.id):
            db.delete(workspace)  # 内容靠 FK CASCADE 跟着走
        db.flush()

        # 剩下的按列扫。users 那一行留到最后 —— 有 CASCADE 的表会自己走,没有的在这里清掉。
        for table, column in _tables_pointing_at_a_person():
            if table == "users":
                continue
            db.execute(text(f"DELETE FROM {table} WHERE {column} = :uid"), {"uid": user.id})
        db.delete(user)
        db.commit()
