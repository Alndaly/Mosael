"""站内通知:发布结果、工作流失败、批量完成等关键事件的持久投递。

与任务总线(jobs/task_events)的分工:任务总线是「进行中的进度」,
通知是「值得留痕的结果」——按用户投递、带已读状态,团队协作申请
(type="team")等未来事件走同一条通道。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Notification, WorkspaceMember, now

# 每个用户最多保留的通知条数,超出的最旧记录随新通知写入被清理。
MAX_PER_USER = 200

#: agent:智能体经 POST /api/notifications 推的那条(工作流的通知节点对应物)。
NOTIFICATION_TYPES = ("system", "publish", "workflow", "team", "agent")


def notify(
    db: Session,
    workspace_id: str,
    *,
    type: str,
    title: str,
    body: str = "",
    link: str | None = None,
    payload: dict[str, Any] | None = None,
    user_id: str | None = None,
) -> list[Notification]:
    """写入通知(不 commit,随调用方事务落库)。

    type 必须在 NOTIFICATION_TYPES 里。以前这张清单是**摆设** —— 没有任何地方拿它校验,
    我加 "agent" 那次它一声没吭,而前端是按 type 查图标表的:表里没有就退化成一个通用铃铛,
    看着像正常通知,其实是个没人认领的类型。清单要么管事,要么不该存在。

    user_id 为空时扇出给工作区全部成员——团队模式下每个成员各一条、
    各自维护已读状态。
    """
    if type not in NOTIFICATION_TYPES:
        raise ValueError(f"未知的通知类型 {type!r};合法值:{NOTIFICATION_TYPES}")
    if user_id is not None:
        recipients = [user_id]
    else:
        recipients = list(
            db.scalars(select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == workspace_id))
        )
    created: list[Notification] = []
    for recipient in recipients:
        item = Notification(
            workspace_id=workspace_id,
            user_id=recipient,
            type=type,
            title=title[:200],
            body=body[:2000],
            link=link,
            payload=payload or {},
        )
        db.add(item)
        created.append(item)
        _trim(db, recipient)
    return created


def _trim(db: Session, user_id: str) -> None:
    stale = list(
        db.scalars(
            select(Notification.id)
            .where(Notification.user_id == user_id)
            .order_by(Notification.created_at.desc())
            .offset(MAX_PER_USER - 1)
        )
    )
    if stale:
        for item in db.scalars(select(Notification).where(Notification.id.in_(stale))):
            db.delete(item)


def mark_read(db: Session, notification: Notification) -> Notification:
    if notification.read_at is None:
        notification.read_at = now()
    return notification


def mark_all_read(db: Session, workspace_id: str, user_id: str) -> int:
    stmt = select(Notification).where(
        Notification.workspace_id == workspace_id,
        Notification.user_id == user_id,
        Notification.read_at.is_(None),
    )
    count = 0
    stamp = now()
    for item in db.scalars(stmt):
        item.read_at = stamp
        count += 1
    return count


def clear_read(db: Session, workspace_id: str, user_id: str) -> int:
    """删掉自己已读的通知。读过的通知没有第二次价值,却会把面板一直占满 ——
    未读的不动:清空不该顺手把还没看的也带走。"""
    result = db.execute(
        delete(Notification).where(
            Notification.workspace_id == workspace_id,
            Notification.user_id == user_id,
            Notification.read_at.is_not(None),
        )
    )
    return int(result.rowcount or 0)
