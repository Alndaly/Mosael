from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.i18n import tr
from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas import NotificationListOut, NotificationOut, NotifyRequest
from app.db.models import Notification
from app.domain.notifications import use_cases as notifications

router = APIRouter(tags=["notifications"])


@router.post("/notifications", response_model=NotificationOut)
def create_notification(body: NotifyRequest, db: Tx, user: CurrentUser) -> Notification:
    """给工作区成员推一条站内通知。

    工作流的「发送通知」节点走的是同一个领域函数;这条端点是为了让智能体也能用 ——
    同一个能力不该因为入口不同而只存在于一边。
    """
    rows = notifications.post(db, user, body.workspace_id, body.title, body.body)
    if not rows:
        raise HTTPException(status_code=422, detail=tr("routeErr_noNotifiableMembers"))
    return rows[0]


@router.get("/notifications", response_model=NotificationListOut)
def list_notifications(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    unread_only: bool = False,
    limit: int = 50,
) -> NotificationListOut:
    items, unread = notifications.list_mine(db, user, workspace_id, unread_only=unread_only, limit=limit)
    return NotificationListOut(
        items=[NotificationOut.model_validate(item) for item in items],
        unread=unread,
    )


@router.post("/notifications/{notification_id}/read", response_model=NotificationOut)
def read_notification(notification_id: str, db: Tx, user: CurrentUser) -> Notification:
    return notifications.read(db, user, notification_id)


@router.post("/notifications/read-all")
def read_all_notifications(workspace_id: str, db: Tx, user: CurrentUser) -> dict:
    return {"read": notifications.read_all(db, user, workspace_id)}


@router.delete("/notifications/read")
def delete_read_notifications(workspace_id: str, db: Tx, user: CurrentUser) -> dict:
    """清空自己已读的通知。读过的没有第二次价值,却会把面板一直占满;未读的不动。"""
    return {"removed": notifications.clear_read(db, user, workspace_id)}
