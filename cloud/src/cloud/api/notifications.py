"""通知的 HTTP 入口。

路由只做转译:取当前用户、调 `cloud.domain.notifications`、按形状返回。
**登录是硬要求**(`CurrentUser`),而且每个查询都以 `recipient_id == user.id` 收口 ——
这里不写业务规则,也不给别人看别人的通知。
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from cloud.api.deps import CurrentUser, DbSession
from cloud.domain.notifications import (
    count_unread,
    list_notifications,
    mark_read,
)

router = APIRouter(tags=["notifications"])


class ReadIn(BaseModel):
    """要标已读的通知 id。**不传 `ids` = 全部标已读**;传空数组 = 一条都不标。"""

    ids: list[str] | None = None


@router.get("/notifications")
def notifications(
    user: CurrentUser,
    db: DbSession,
    limit: int = 20,
    cursor: str = "",
) -> dict[str, object]:
    items, next_cursor, unread = list_notifications(db, user, limit=limit, cursor=cursor)
    return {"items": items, "next_cursor": next_cursor, "unread": unread}


@router.get("/notifications/unread-count")
def unread_count(user: CurrentUser, db: DbSession) -> dict[str, int]:
    return {"count": count_unread(db, user)}


@router.post("/notifications/read")
def read(
    user: CurrentUser,
    db: DbSession,
    body: ReadIn | None = None,
) -> dict[str, int]:
    # 没有 body 与 `{}` 同义:ids 为 None = 全部标已读。
    return mark_read(db, user, body.ids if body is not None else None)
