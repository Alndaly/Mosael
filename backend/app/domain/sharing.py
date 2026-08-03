from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AgentSession,
    BrowserProfile,
    PublishAccount,
    ResourceShare,
    ScheduledTask,
    User,
)

"""归属与共享。

此前它们是同一件事:把东西放进工作区,既是存储方式**也是**共享方式 —— 于是没有「放进来但仍然是
我的」这种状态。而有四类东西并不是工作区的资产:

    publish_accounts   某人在平台上的登录态
    browser_profiles   某人已登录的浏览器
    agent_sessions     某人的对话
    scheduled_tasks    替某人跑的自动化

拆开之后:`owner_user_id` 说这是谁的,`resource_shares` 里的一行说主人把它放进了哪个工作区。
一条规则覆盖四类,不是四个特例。
"""

#: 资源种类 → (模型, 这一类新建时默认共享给它所在的工作区吗)。
#:
#: **默认值按类别定,而且只在这里定。** 身份与私人对话默认私有;定时任务默认共享 —— 它是团队基建,
#: 归属是为了可追溯与停摆(主人失去权限时该停),不是为了藏起来。把这一条写成一张表而不是散在各处
#: 的 if,是因为「这一类默认给谁看」正是最容易在第二个调用点被写反的东西。
KINDS: dict[str, tuple[type, bool]] = {
    "publish_account": (PublishAccount, False),
    "browser_profile": (BrowserProfile, False),
    "agent_session": (AgentSession, False),
    "scheduled_task": (ScheduledTask, True),
}


class SharingError(ValueError):
    pass


def model_for(kind: str) -> type:
    if kind not in KINDS:
        raise SharingError(f"未知的资源类型:{kind}")
    return KINDS[kind][0]


def claim(db: Session, kind: str, resource: Any, owner: User) -> None:
    """记下归属,并按这一类的默认值决定要不要顺手共享给它所在的工作区。

    建资源的地方调用它 —— 主人是**建的那个人**,不是工作区的 owner(后者只是迁移老数据时的近似)。
    """
    _model, share_by_default = KINDS[kind]
    resource.owner_user_id = owner.id
    if share_by_default and resource.workspace_id:
        share(db, kind, resource.id, resource.workspace_id, owner.id)


def _companions(db: Session, kind: str, resource_id: str) -> list[tuple[str, str]]:
    """和它同属一个身份、必须一起共享/一起收回的东西。

    发布账号与它的浏览器档案是**同一个身份的两半**(见 publish.create_account:建账号时顺带建档,
    共用同一个登录分区)。只共享一半会得到一个说不通的状态:看得见账号却没有那个已登录的浏览器,
    或者反过来。把这条耦合放在这里而不是每个调用点上,因为它正是第二个调用点会忘记的那种东西。
    """
    pairs = [(kind, resource_id)]
    if kind == "publish_account":
        account = db.get(PublishAccount, resource_id)
        if account is not None and account.profile_id:
            pairs.append(("browser_profile", account.profile_id))
    elif kind == "browser_profile":
        account = db.scalar(select(PublishAccount).where(PublishAccount.profile_id == resource_id))
        if account is not None:
            pairs.append(("publish_account", account.id))
    return pairs


def share(db: Session, kind: str, resource_id: str, workspace_id: str, shared_by: str) -> None:
    """把它放进一个工作区。重复调用不产生第二行。"""
    for companion_kind, companion_id in _companions(db, kind, resource_id):
        _share_one(db, companion_kind, companion_id, workspace_id, shared_by)


def _share_one(db: Session, kind: str, resource_id: str, workspace_id: str, shared_by: str) -> None:
    existing = db.scalar(
        select(ResourceShare).where(
            ResourceShare.kind == kind,
            ResourceShare.resource_id == resource_id,
            ResourceShare.workspace_id == workspace_id,
        )
    )
    if existing is not None:
        return
    db.add(
        ResourceShare(
            kind=kind, resource_id=resource_id, workspace_id=workspace_id, shared_by=shared_by
        )
    )


def unshare(db: Session, kind: str, resource_id: str, workspace_id: str) -> None:
    for companion_kind, companion_id in _companions(db, kind, resource_id):
        for row in db.scalars(
            select(ResourceShare).where(
                ResourceShare.kind == companion_kind,
                ResourceShare.resource_id == companion_id,
                ResourceShare.workspace_id == workspace_id,
            )
        ):
            db.delete(row)


def is_shared_with(db: Session, kind: str, resource_id: str, workspace_id: str) -> bool:
    return (
        db.scalar(
            select(ResourceShare).where(
                ResourceShare.kind == kind,
                ResourceShare.resource_id == resource_id,
                ResourceShare.workspace_id == workspace_id,
            )
        )
        is not None
    )


def visible_filter(kind: str, user: User, workspace_id: str):
    """「这个人在这个工作区里看得见哪些」的 SQL 条件。

    两种看得见:**是我的**,或者**有人把它共享进了这个工作区**。前一半不能省 —— 主人自己必须始终
    看得见自己的东西,哪怕他从没共享过。
    """
    model = model_for(kind)
    shared = select(ResourceShare.resource_id).where(
        ResourceShare.kind == kind, ResourceShare.workspace_id == workspace_id
    )
    return (model.owner_user_id == user.id) | (model.id.in_(shared))


def may_use(db: Session, kind: str, resource: Any, user: User) -> bool:
    """他能不能**用**这一份,而不只是看得见。

    看得见不够:猜到 id 也得用不了,否则「私有」只是列表上的一层遮挡。
    """
    if resource is None:
        return False
    if resource.owner_user_id == user.id:
        return True
    if not resource.workspace_id:
        return False
    return (
        db.scalar(
            select(ResourceShare).where(
                ResourceShare.kind == kind,
                ResourceShare.resource_id == resource.id,
                ResourceShare.workspace_id == resource.workspace_id,
            )
        )
        is not None
    )


def shared_workspaces(db: Session, kind: str, resource_id: str) -> list[str]:
    return [
        row.workspace_id
        for row in db.scalars(
            select(ResourceShare).where(
                ResourceShare.kind == kind, ResourceShare.resource_id == resource_id
            )
        )
    ]
