"""工作区成员与邀请:谁在哪个工作区里、怎么被邀请进来。账号本身(建号、改密、删号)在 accounts。

Workspace membership operations with the "last owner" invariant.

A workspace must always keep at least one owner — you can't demote or remove the last
one, or the workspace becomes unmanageable. That check-then-write must be atomic, so the
mutating ops run under a module lock (mirrors the predecessor project's core/workspaces.py RLock).
Actor-level authorization (who may call these) is enforced in the route layer.
"""
from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.core.i18n import LocalizedError, tr
from app.core.token_digest import token_digest
from app.core.unit_of_work import after_commit
from app.db.models import (
    InviteLink,
    Notification,
    User,
    Workspace,
    WorkspaceInvitation,
    WorkspaceMember,
    now,
    now as _now,
)
from app.domain import deployment, notifications as notifications_svc
from app.domain.usernames import normalize_username
from app.domain.permissions import PermissionDenied
from app.domain.agent.skills.store import delete_workspace_files as delete_workspace_skills
from app.domain.storage_cleanup import delete_workspace_files

#: 成员变动的「先查再改」(最后一个所有者、重复邀请、邀请已处理)靠这把锁串行;删账号(accounts.delete_user_account)也拿它。**锁里的提交是有意的**:
#: 锁放开之前就得落库 —— 只 flush 的话,下一个拿到锁的请求读到的还是提交前的样子,两人同时降级
#: 就能把工作区降到一个所有者都没有。
MEMBERSHIP_LOCK = threading.RLock()


class MemberError(LocalizedError):
    """Domain error → mapped to HTTP 400/409 by the route. 带文案 key(`memberErr_*`)。"""


# ---------------- 邀请链接(ADR 0054) ----------------

#: 邀请链接多久过期(D49)。用一次就作废;和此前的注册邀请码一样是 7 天。
INVITE_TTL = timedelta(days=7)
#: 链接能给的工作区角色。所有者不经链接给 —— 只有所有者能在成员列表里当面授予(见 ensure_may_touch_owner)。
LINK_ROLES = ("admin", "editor", "viewer")


@dataclass(frozen=True)
class IssuedLink:
    """刚发出去的一张链接。`code` 是原文,只在这一次给发链接的人 —— 库里只有哈希。"""

    link: InviteLink
    code: str


@dataclass(frozen=True)
class Joined:
    """凭链接进了一个工作区:进的是哪个、什么角色、主人是谁(界面上那句「已加入」说的就是这几样)。"""

    workspace: Workspace
    role: str
    owner_name: str
    #: 本来就是成员(不是凭这张链接进来的):什么都没改,界面也不给「撤销」—— 撤销会把原有的成员身份一起退掉。
    already_member: bool


def issue_invite_link(db: Session, creator: User, *, workspace_id: str | None, role: str = "", note: str = "") -> IssuedLink:
    """发一张邀请链接。`workspace_id` 为空是只进这台部署的(此前的注册邀请码)。不提交。

    谁能发、能发哪种,由调用方先判(工作区的 `members` 权限 / 部署管理员);这里只记一件和人有关的事:
    **部署管理员发的链接自带「能顺带注册」**(D48),工作区管理员发的要请部署管理员放行,或者部署本来开放注册。
    """
    if workspace_id is not None and role not in LINK_ROLES:
        raise MemberError("memberErr_linkRole", roles=" / ".join(LINK_ROLES))
    code = secrets.token_urlsafe(24)
    link = InviteLink(
        code_hash=token_digest(code),
        code_hint=code[-4:],
        workspace_id=workspace_id,
        role=role if workspace_id is not None else "",
        created_by=creator.id,
        note=note.strip()[:120],
        signup_approved_by=creator.id if creator.is_deployment_admin else None,
        expires_at=now() + INVITE_TTL,
    )
    db.add(link)
    db.flush()
    return IssuedLink(link=link, code=code)


def find_invite_link(db: Session, code: str) -> InviteLink | None:
    """按原文找那张链接(比的是哈希)。空串、找不到都是 None。"""
    code = (code or "").strip()
    if not code:
        return None
    return db.scalar(select(InviteLink).where(InviteLink.code_hash == token_digest(code)))


def link_state(link: InviteLink) -> str:
    """`open`(还能用)/ `used` / `revoked` / `expired`。撤回、用过排在过期前面:说得出是哪件事发生了。"""
    if link.revoked_at is not None:
        return "revoked"
    if link.used_by:
        return "used"
    if link.expires_at <= now():
        return "expired"
    return "open"


#: 一张链接用不了时说的是哪件事(找不到的另说:memberErr_linkUnknown)。
_LINK_STATE_ERRORS = {"used": "memberErr_linkUsed", "revoked": "memberErr_linkRevoked", "expired": "memberErr_linkExpired"}


def link_allows_signup(db: Session, link: InviteLink) -> bool:
    """还没账号的人能不能凭它注册:部署管理员放过行(他自己发的自带),或者部署本来开放注册(D48)。"""
    return bool(link.signup_approved_by) or deployment.open_registration(db)


def usable_invite(db: Session, code: str) -> InviteLink | None:
    """还能用的那张链接;看不懂的码、用过的、撤回的、过期的一律当作没有。"""
    link = find_invite_link(db, code)
    return link if link is not None and link_state(link) == "open" else None


def adopt_orphan_workspaces(db: Session, user: User) -> None:
    """本机升级路径:库里还没有任何成员关系时,第一个账号继承登录之前建的那些工作区。"""
    if db.scalar(select(WorkspaceMember).limit(1)) is not None:
        return
    for workspace in db.scalars(select(Workspace)):
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))


def workspace_name(db: Session, workspace_id: str) -> str:
    """工作区在界面上叫什么;不在了就回它的 id(邀请、链接里还要说得出是哪个)。"""
    workspace = db.get(Workspace, workspace_id)
    return workspace.name if workspace is not None else workspace_id


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
    username = normalize_username(username)
    with MEMBERSHIP_LOCK:
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


def sent_invitations(db: Session, workspace_id: str) -> list[tuple[WorkspaceInvitation, User, User]]:
    """这个工作区发出去、对方还没应答的邀请:(邀请, 受邀人, 邀请人)。团队页把它们列在成员下面,能撤回 ——
    此前发出去就看不见了,邀错了人只能等对方拒绝(体检 UM-07)。"""
    invitee, inviter = aliased(User), aliased(User)
    rows = db.execute(
        select(WorkspaceInvitation, invitee, inviter)
        .join(invitee, invitee.id == WorkspaceInvitation.invitee_id)
        .join(inviter, inviter.id == WorkspaceInvitation.inviter_id)
        .where(WorkspaceInvitation.workspace_id == workspace_id, WorkspaceInvitation.status == "pending")
        .order_by(WorkspaceInvitation.created_at.desc())
    ).all()
    return [(inv, to, by) for inv, to, by in rows]


def revoke_invitation(db: Session, workspace_id: str, invitation_id: str) -> None:
    """撤回一条还没应答的邀请。对方通知里那张「接受 / 拒绝」卡随之消失(卡片只列待处理的),那条「邀请你加入」
    的通知也一起删掉 —— 留着它,点进去是一句「邀请已处理过」。不提交:交给入口的 Tx。"""
    invitation = db.get(WorkspaceInvitation, invitation_id)
    if invitation is None or invitation.workspace_id != workspace_id:
        raise MemberError("memberErr_inviteNotFound")
    if invitation.status != "pending":
        raise MemberError("memberErr_inviteHandled")
    invitation.status = "revoked"
    invitation.responded_at = now()
    db.query(Notification).filter(
        Notification.user_id == invitation.invitee_id,
        func.json_extract(Notification.payload, "$.invitation_id") == invitation.id,
    ).delete(synchronize_session=False)
    db.flush()


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

    with MEMBERSHIP_LOCK:
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


def use_invite_link(db: Session, link: InviteLink, user: User) -> bool:
    """`user` 用掉这张链接:记下谁、什么时候;带着工作区的,建成员行(本来就是成员就不动)并告诉发链接的人。
    回「新进了工作区」。不提交。"""
    link.used_by = user.id
    link.used_at = now()
    if link.workspace_id is None:
        return False
    if db.get(WorkspaceMember, {"workspace_id": link.workspace_id, "user_id": user.id}) is not None:
        return False
    db.add(WorkspaceMember(workspace_id=link.workspace_id, user_id=user.id, role=link.role))
    workspace = db.get(Workspace, link.workspace_id)
    notifications_svc.notify(
        db,
        link.workspace_id,
        type="team",
        title=tr("memberNotice_joinedByLink", name=user.display_name, workspace=workspace.name if workspace else ""),
        body="",
        payload={"kind": "invite-link-used", "invite_link_id": link.id},
        user_id=link.created_by,
    )
    db.flush()
    return True


def _owner_name(db: Session, workspace_id: str) -> str:
    owner = db.scalar(
        select(User)
        .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
        .where(WorkspaceMember.workspace_id == workspace_id, WorkspaceMember.role == "owner")
        .order_by(WorkspaceMember.created_at.asc())
        .limit(1)
    )
    return (owner.display_name or owner.username) if owner is not None else ""


def redeem_invite_link(db: Session, user: User, code: str) -> Joined:
    """已登录的人打开一张工作区邀请链接:直接成为成员(D51)。不提交。

    **对用过它的那个人是幂等的**:注册时已经凭它进来了、或者同一个人再点一次,回同一个工作区,什么都不改。
    本来就是这个工作区的成员时也不消耗它(链接是一次性的,留着还能转给真正要它的人)。
    """
    link = find_invite_link(db, code)
    if link is None:
        raise MemberError("memberErr_linkUnknown")
    workspace = db.get(Workspace, link.workspace_id) if link.workspace_id else None
    if link.workspace_id is None:
        raise MemberError("memberErr_linkIsForSignup")
    if workspace is None:
        raise MemberError("memberErr_linkUnknown")
    member = db.get(WorkspaceMember, {"workspace_id": workspace.id, "user_id": user.id})
    if link.used_by == user.id and member is not None:
        #: 就是凭这张进来的(刚注册完、或者又点了一次):照「加入了」回,界面照样给撤销。
        return Joined(workspace=workspace, role=member.role, owner_name=_owner_name(db, workspace.id), already_member=False)
    state = link_state(link)
    if state != "open":
        raise MemberError(_LINK_STATE_ERRORS[state])
    if member is not None:
        return Joined(workspace=workspace, role=member.role, owner_name=_owner_name(db, workspace.id), already_member=True)
    use_invite_link(db, link, user)
    return Joined(workspace=workspace, role=link.role, owner_name=_owner_name(db, workspace.id), already_member=False)


def preview_invite_link(db: Session, code: str) -> dict[str, object] | None:
    """打开链接、还没登录的那一屏要知道的:进哪个工作区、谁邀请的、什么角色、还能不能用、没账号的人能不能凭它注册。
    找不到回 None。只给拿着原文的人看(原文就是凭据)。"""
    link = find_invite_link(db, code)
    if link is None:
        return None
    workspace = db.get(Workspace, link.workspace_id) if link.workspace_id else None
    inviter = db.get(User, link.created_by)
    return {
        "workspace_name": workspace.name if workspace is not None else "",
        "inviter_name": (inviter.display_name or inviter.username) if inviter is not None else "",
        "role": link.role,
        "state": link_state(link),
        "allows_signup": link_allows_signup(db, link),
    }


def workspace_links(db: Session, workspace_id: str) -> list[InviteLink]:
    """这个工作区发出去、还能用的链接(团队页和按用户名的邀请列在一起,能撤回)。"""
    return [
        link
        for link in db.scalars(
            select(InviteLink)
            .where(InviteLink.workspace_id == workspace_id, InviteLink.used_by.is_(None), InviteLink.revoked_at.is_(None))
            .order_by(InviteLink.created_at.desc())
        )
        if link_state(link) == "open"
    ]


def deployment_links(db: Session) -> list[InviteLink]:
    """不带工作区的邀请(管理页「成员」那一节;含此前的注册邀请码,见迁移)。最近 50 张。"""
    return list(
        db.scalars(
            select(InviteLink).where(InviteLink.workspace_id.is_(None)).order_by(InviteLink.created_at.desc()).limit(50)
        )
    )


def links_awaiting_signup(db: Session) -> list[InviteLink]:
    """工作区管理员请部署管理员放行、还没放行的那些(还能用的才列)。"""
    return [
        link
        for link in db.scalars(
            select(InviteLink)
            .where(InviteLink.signup_requested_at.is_not(None), InviteLink.signup_approved_by.is_(None))
            .order_by(InviteLink.signup_requested_at.desc())
        )
        if link_state(link) == "open"
    ]


def revoke_invite_link(db: Session, link_id: str, *, workspace_id: str | None) -> None:
    """撤回一张还没用过的链接。`workspace_id` 是从哪一边撤的(工作区团队页 / 管理页的不带工作区那一节),
    对不上就当作没有。不提交。"""
    link = db.get(InviteLink, link_id)
    if link is None or link.workspace_id != workspace_id:
        raise MemberError("memberErr_linkUnknown")
    if link.used_by:
        raise MemberError(_LINK_STATE_ERRORS["used"])
    if link.revoked_at is None:
        link.revoked_at = now()
    db.flush()


def request_signup(db: Session, link_id: str, *, workspace_id: str, requester: User) -> InviteLink:
    """工作区管理员请部署管理员放行:让还没账号的人也能凭这张链接注册(D48)。给每位部署管理员发一条通知,
    管理页「等你放行」里也列着。重复请求不重复通知。不提交。"""
    link = db.get(InviteLink, link_id)
    if link is None or link.workspace_id != workspace_id or link_state(link) != "open":
        raise MemberError("memberErr_linkUnknown")
    if link.signup_approved_by or link.signup_requested_at is not None:
        return link
    link.signup_requested_at = now()
    workspace = db.get(Workspace, workspace_id)
    for admin in db.scalars(select(User).where(User.is_deployment_admin.is_(True))):
        places = [ws for ws, _role in workspaces_of(db, admin.id)]
        #: 通知挂在某个工作区下;放行这件事和哪个工作区无关,挂在他自己在的那一个(优先就是这张链接的工作区)。
        place = next((ws for ws in places if ws.id == workspace_id), places[0] if places else None)
        if place is None:
            continue
        notifications_svc.notify(
            db,
            place.id,
            type="team",
            title=tr("memberNotice_signupRequested", name=requester.display_name,
                     workspace=workspace.name if workspace else ""),
            body="",
            link="#/admin",
            payload={"kind": "invite-link-signup", "invite_link_id": link.id},
            user_id=admin.id,
        )
    db.flush()
    return link


def approve_signup(db: Session, link_id: str, *, admin: User) -> InviteLink:
    """部署管理员放行:这张链接从此也能让还没账号的人注册。调用方先确认他是部署管理员。不提交。"""
    link = db.get(InviteLink, link_id)
    if link is None or link_state(link) != "open":
        raise MemberError("memberErr_linkUnknown")
    link.signup_approved_by = admin.id
    db.flush()
    return link


def ensure_may_touch_owner(
    db: Session, workspace_id: str, user_id: str, *, actor_role: str, new_role: str | None = None
) -> None:
    """**只有所有者能授予、改动或移除所有者。** 否则管理员能给自己(或同伙)升成所有者,或者把真正的
    所有者请出去。`new_role` 是要改成的角色(移除成员时不给)。目标不是成员时不在这里管,由后面的操作报。"""
    target = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id})
    touches_owner = new_role == "owner" or (target is not None and target.role == "owner")
    if touches_owner and actor_role != "owner":
        raise PermissionDenied("memberErr_onlyOwnerTouchesOwner")


def set_role(db: Session, workspace_id: str, user_id: str, role: str) -> WorkspaceMember:
    with MEMBERSHIP_LOCK:
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
    with MEMBERSHIP_LOCK:
        member = db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id})
        if member is None:
            raise MemberError("memberErr_notMember")
        if member.role == "owner" and owners_count(db, workspace_id) <= 1:
            raise MemberError("memberErr_lastOwnerRemove")
        db.delete(member)
        db.commit()





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


def delete_workspace(db: Session, workspace_id: str) -> None:
    """删工作区。成员和工作区里的各种资源由外键 CASCADE 带走;**文件不会** —— 素材、音色、LUT、字体、3D 模型
    (都在 media/ 下按工作区分目录,见 media/paths.WORKSPACE_MEDIA_CATEGORIES)、技能文件夹,由这里显式清掉。

    此前只清了 3D 模型和技能:素材原件、代理、缩略图、音色样本全留在盘上,而确认框写着「永久移除」。"""

    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        return
    db.delete(workspace)
    # 文件在行真的删掉(提交成功)之后再清:回滚了的话工作区还在,它的文件不能先没了。
    after_commit(db, lambda: delete_workspace_files(workspace_id))
    # 技能文件夹也归工作区(ADR 0040 §3):索引行由外键带走,文件夹在这里删。
    after_commit(db, lambda: delete_workspace_skills(workspace_id))
