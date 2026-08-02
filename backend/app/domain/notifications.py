"""站内通知:发布结果、工作流失败、批量完成等关键事件的持久投递。

与任务总线(jobs/task_events)的分工:任务总线是「进行中的进度」,
通知是「值得留痕的结果」——按用户投递、带已读状态,团队协作申请
(type="team")等未来事件走同一条通道。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
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

    user_id 为空时扇出给工作区全部成员——团队模式下每个成员各一条、
    各自维护已读状态。
    """
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
