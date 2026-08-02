from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import NotificationListOut, NotificationOut, NotifyRequest
from app.core.permissions import ensure_workspace_access
from app.db.models import Notification
from app.domain.notifications import mark_all_read, mark_read, notify

router = APIRouter(tags=["notifications"])


@router.post("/notifications", response_model=NotificationOut)
def create_notification(body: NotifyRequest, db: DbSession, user: CurrentUser) -> Notification:
    """给工作区成员推一条站内通知。

    工作流的「发送通知」节点走的是同一个领域函数;这条端点是为了让智能体也能用 ——
    同一个能力不该因为入口不同而只存在于一边。
    """
    ensure_workspace_access(db, user, body.workspace_id)
    rows = notify(db, body.workspace_id, type="agent", title=body.title, body=body.body)
    db.commit()
    if not rows:
        raise HTTPException(status_code=422, detail="该工作区没有可通知的成员")
    db.refresh(rows[0])
    return rows[0]


@router.get("/notifications", response_model=NotificationListOut)
def list_notifications(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    unread_only: bool = False,
    limit: int = 50,
) -> NotificationListOut:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(Notification).where(
        Notification.workspace_id == workspace_id,
        Notification.user_id == user.id,
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    items = list(db.scalars(stmt.order_by(Notification.created_at.desc()).limit(min(limit, 100))))
    unread = db.scalar(
        select(func.count())
        .select_from(Notification)
        .where(
            Notification.workspace_id == workspace_id,
            Notification.user_id == user.id,
            Notification.read_at.is_(None),
        )
    )
    return NotificationListOut(
        items=[NotificationOut.model_validate(item) for item in items],
        unread=int(unread or 0),
    )


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def read_notification(notification_id: str, db: DbSession, user: CurrentUser) -> Notification:
    item = db.get(Notification, notification_id)
    if item is None or item.user_id != user.id:
        raise HTTPException(status_code=404, detail="Notification not found")
    mark_read(db, item)
    db.commit()
    db.refresh(item)
    return item


@router.post("/notifications/read-all")
def read_all_notifications(workspace_id: str, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_access(db, user, workspace_id)
    count = mark_all_read(db, workspace_id, user.id)
    db.commit()
    return {"read": count}
