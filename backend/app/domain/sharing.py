from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    AgentSession,
    BrowserProfile,
    GenerationSession,
    PublishAccount,
    ResourceShare,
    ScheduledTask,
    User,
)

"""归属与共享。

此前它们是同一件事:把东西放进工作区,既是存储方式**也是**共享方式 —— 于是没有「放进来但仍然是
我的」这种状态。而有五类东西并不是工作区的资产:

    publish_accounts    某人在平台上的登录态
    browser_profiles    某人已登录的浏览器
    agent_sessions      某人的对话
    generation_sessions 某人的生成记录
    scheduled_tasks     替某人跑的自动化

拆开之后:`owner_user_id` 说这是谁的,`resource_shares` 里的一行说主人把它放进了哪个工作区。
一条规则覆盖五类,不是五个特例。
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
    "generation_session": (GenerationSession, False),
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


def forget(db: Session, kind: str, resource_id: str) -> None:
    """这份东西没了 —— 把它在**所有**工作区里的共享记录一起清掉。

    和 `unshare` 不同:那个是「从这个工作区里收回」,是用户的一次决定;这个是删除时的收尾。

    必须显式做,`resource_shares.resource_id` 是**多态**引用(同一列指向五张不同的表),
    没法建外键、也就没有级联。漏掉的后果不是报错:记录留在库里指向一个不存在的 id,
    越攒越多;而真正咬人的是**同名 kind 的下一次统计**会把它们算进去 —— 真库里 19 条
    generation_session 共享记录,16 条指向早就删掉的会话。
    """
    for row in db.scalars(
        select(ResourceShare).where(ResourceShare.kind == kind, ResourceShare.resource_id == resource_id)
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


def shared_ids(db: Session, kind: str, workspace_id: str) -> set[str]:
    """这个工作区里被共享进来的这一类资源 id。一次查询顶一整个列表。"""
    return set(
        db.scalars(
            select(ResourceShare.resource_id).where(
                ResourceShare.kind == kind, ResourceShare.workspace_id == workspace_id
            )
        )
    )


def annotate(db: Session, kind: str, rows: list, user: User, workspace_id: str) -> list:
    """给一批直接按 ORM 序列化出去的行标上 `is_mine` / `shared`。

    界面要回答两个问题:这是不是我的(决定给不给共享开关),以及它现在在不在这个工作区里。
    两个都不是表上的列 —— 一个要和当前用户比,一个在 resource_shares 里。自己拼 Out 对象的路由
    直接用 `shared_ids`;这两条路共用同一个查询,免得第二处列表算出不同的答案。
    """
    shared = shared_ids(db, kind, workspace_id)
    for row in rows:
        # 非映射属性:只为序列化而挂,不会被 flush 写回。
        row.is_mine = row.owner_user_id == user.id
        row.shared = row.id in shared
    return rows


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
