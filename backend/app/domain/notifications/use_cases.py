"""站内通知的用例:按工作区过只读闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

通知按人投递:读、标已读、清空都只碰**自己**的那几条,所以只要是工作区的人就行,不点名权限。
推一条给全体成员同理 —— 它不改任何工程内容。不提交事务。
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Notification, User
from app.domain import notifications as notifications_svc
from app.domain.permissions import NotVisible, ensure_workspace_access

#: 列表一次最多给多少条。
LIST_LIMIT = 100


def post(db: Session, user: User, workspace_id: str, title: str, body: str = "") -> list[Notification]:
    """给工作区成员推一条(智能体经 POST /api/notifications 用,工作流的通知节点对应物)。没人可推就是空表。"""
    ensure_workspace_access(db, user, workspace_id)
    rows = notifications_svc.notify(db, workspace_id, type="agent", title=title, body=body)
    db.flush()
    return rows


def list_mine(
    db: Session, user: User, workspace_id: str, *, unread_only: bool = False, limit: int = 50
) -> tuple[list[Notification], int]:
    """自己在这个工作区的通知(新的在前)和未读总数。"""
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(Notification).where(
        Notification.workspace_id == workspace_id,
        Notification.user_id == user.id,
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    items = list(db.scalars(stmt.order_by(Notification.created_at.desc()).limit(min(limit, LIST_LIMIT))))
    unread = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.workspace_id == workspace_id,
            Notification.user_id == user.id,
            Notification.read_at.is_(None),
        )
    )
    return items, int(unread or 0)


def read(db: Session, user: User, notification_id: str) -> Notification:
    """别人的和不存在的同一个回答。"""
    item = db.get(Notification, notification_id)
    if item is None or item.user_id != user.id:
        raise NotVisible("Notification not found")
    notifications_svc.mark_read(db, item)
    db.flush()
    return item


def read_all(db: Session, user: User, workspace_id: str) -> int:
    ensure_workspace_access(db, user, workspace_id)
    return notifications_svc.mark_all_read(db, workspace_id, user.id)


def clear_read(db: Session, user: User, workspace_id: str) -> int:
    """清空自己已读的通知;未读的不动。"""
    ensure_workspace_access(db, user, workspace_id)
    return notifications_svc.clear_read(db, workspace_id, user.id)
