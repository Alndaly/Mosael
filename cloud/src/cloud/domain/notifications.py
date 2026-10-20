"""通知:谁对谁的分享点了赞 / 收藏 / 评论。

规则只有一条来源,全在这个模块里;`api/` 只转发。

- **收件人永远是分享作者。** 自己给自己的分享点赞 / 收藏 / 评论 → 不产生通知。
- **一个槽位最多一条未读。** 槽位 = `(recipient, actor, share, kind)`;数据库用一条
  `WHERE read_at IS NULL` 的部分唯一索引兜底。同一个人反复点赞 / 取消 / 再点赞,
  或者连续评论同一条分享,最多堆出一条未读。已读之后的新互动才新开一行(历史保留)。
- 评论的未读行会把 `comment_id` 刷新到最新那条,`comment_preview` 因此总是指向最新评论。
- **取消点赞 / 收藏:** 删掉这条互动对应的**未读**通知。已读的那条保留 —— 它是历史记录,
  不是"他现在还赞着"的陈述;未读的"他点赞了"在他取消之后才是一句假话。
- **删评论:** 按 `comment_id` 把通知一起删(读没读过都删)。
- **分享软删:** 不删通知数据;读取时 join 掉 `status='listed'`,未读数也不把它算进去。
- 公开形状里 `actor` 只用 `public_user()` 的公开身份(含 `official`),**email 永远不出现**;`comment_preview`
  是原文按字符截断(不渲染 markdown、不做实体转义),和评论列表的口径一致。
"""

from __future__ import annotations

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloud.domain.identity import public_user
from cloud.models import (
    CloudShare,
    CloudShareComment,
    CloudShareNotification,
    CloudUser,
    now,
)
from cloud.pagination import after_clause, clamp_limit, decode_cursor, encode_cursor

NOTIFICATION_KINDS = ("like", "favorite", "comment")

#: 列表里能看见的通知:分享还在架上。软删的分享不删行,只在这里过滤掉。
#: 与 `cloud.domain.shares.SHARE_STATUS_LISTED` 同值;本模块不 import shares(反过来是它 import 本模块)。
VISIBLE_SHARE_STATUS = "listed"

#: `comment_preview` 的上限是字符数,不是字节数。
MAX_COMMENT_PREVIEW = 120


def notify_interaction(
    db: Session,
    *,
    share: CloudShare,
    actor: CloudUser,
    kind: str,
    comment_id: str | None = None,
) -> None:
    """记一次互动。自己对自己的分享直接返回;同一槽位已有未读时不堆第二行。"""
    recipient_id = share.owner_user_id
    if recipient_id == actor.id:
        return

    existing = db.scalar(
        select(CloudShareNotification).where(
            CloudShareNotification.recipient_id == recipient_id,
            CloudShareNotification.actor_id == actor.id,
            CloudShareNotification.share_id == share.id,
            CloudShareNotification.kind == kind,
            CloudShareNotification.read_at.is_(None),
        )
    )
    if existing is not None:
        if _refresh_unread(existing, kind=kind, comment_id=comment_id):
            db.commit()
        return

    db.add(
        CloudShareNotification(
            recipient_id=recipient_id,
            actor_id=actor.id,
            share_id=share.id,
            kind=kind,
            comment_id=comment_id,
        )
    )
    try:
        db.commit()
    except IntegrityError:
        # 并发下另一条请求先插了同一个未读槽位:未读已经有一条,够了。
        db.rollback()


def _refresh_unread(
    notification: CloudShareNotification, *, kind: str, comment_id: str | None
) -> bool:
    """连续评论时把未读指向最新那条评论;点赞 / 收藏的重复事件什么都不改。"""
    if kind != "comment" or comment_id is None or notification.comment_id == comment_id:
        return False
    notification.comment_id = comment_id
    notification.created_at = now()
    return True


def withdraw_interaction(
    db: Session, *, share: CloudShare, actor: CloudUser, kind: str
) -> None:
    """取消点赞 / 收藏:这条互动对应的**未读**通知不再成立,删掉。已读的历史不动。"""
    if share.owner_user_id == actor.id:
        return
    db.execute(
        delete(CloudShareNotification).where(
            CloudShareNotification.recipient_id == share.owner_user_id,
            CloudShareNotification.actor_id == actor.id,
            CloudShareNotification.share_id == share.id,
            CloudShareNotification.kind == kind,
            CloudShareNotification.read_at.is_(None),
        )
    )
    db.commit()


def forget_comment(db: Session, comment_id: str) -> None:
    """删评论时把对应通知一起删(读没读过都删)。**不 commit**,和调用方的删除同一个事务。"""
    db.execute(delete(CloudShareNotification).where(CloudShareNotification.comment_id == comment_id))


# ---------------------------------------------------------------- 读取


def list_notifications(
    db: Session,
    user: CloudUser,
    *,
    limit: int | None = None,
    cursor: str = "",
) -> tuple[list[dict[str, object]], str | None, int]:
    """本人的通知,新序在前;同时给出**未读总数**(不是本页条数)。"""
    size = clamp_limit(limit)
    stmt = _visible(db, user)
    after = decode_cursor(cursor, 2)
    if after is not None:
        stmt = stmt.where(
            after_clause(
                [CloudShareNotification.created_at, CloudShareNotification.id], after
            )
        )
    rows = list(
        db.scalars(
            stmt.order_by(
                CloudShareNotification.created_at.desc(), CloudShareNotification.id.desc()
            ).limit(size + 1)
        )
    )
    next_cursor = (
        encode_cursor([rows[size - 1].created_at, rows[size - 1].id]) if len(rows) > size else None
    )
    return _serialize_many(db, rows[:size]), next_cursor, count_unread(db, user)


def count_unread(db: Session, user: CloudUser) -> int:
    total = db.scalar(
        select(func.count())
        .select_from(CloudShareNotification)
        .join(CloudShare, CloudShare.id == CloudShareNotification.share_id)
        .where(
            CloudShareNotification.recipient_id == user.id,
            CloudShareNotification.read_at.is_(None),
            CloudShare.status == VISIBLE_SHARE_STATUS,
        )
    )
    return int(total or 0)


def mark_read(
    db: Session, user: CloudUser, ids: list[str] | None
) -> dict[str, int]:
    """把本人的未读标成已读。`ids` 为空(None/不传)= 全部;`[]` = 一条都不标。

    别人的 id 只会匹配到 0 行 —— 不报 403,也不泄露那个 id 存不存在。
    """
    stmt = update(CloudShareNotification).where(
        CloudShareNotification.recipient_id == user.id,
        CloudShareNotification.read_at.is_(None),
    )
    if ids is not None:
        stmt = stmt.where(CloudShareNotification.id.in_(ids))
    result = db.execute(stmt.values(read_at=now()))
    db.commit()
    return {"marked": int(result.rowcount or 0), "unread": count_unread(db, user)}


def _visible(db: Session, user: CloudUser):
    return (
        select(CloudShareNotification)
        .join(CloudShare, CloudShare.id == CloudShareNotification.share_id)
        .where(
            CloudShareNotification.recipient_id == user.id,
            CloudShare.status == VISIBLE_SHARE_STATUS,
        )
    )


def _serialize_many(
    db: Session, rows: list[CloudShareNotification]
) -> list[dict[str, object]]:
    if not rows:
        return []
    actor_ids = {row.actor_id for row in rows}
    share_ids = {row.share_id for row in rows}
    comment_ids = {row.comment_id for row in rows if row.comment_id}

    actors = {
        actor.id: actor
        for actor in db.scalars(select(CloudUser).where(CloudUser.id.in_(actor_ids)))
    }
    shares = {
        share.id: share
        for share in db.scalars(select(CloudShare).where(CloudShare.id.in_(share_ids)))
    }
    previews = (
        {
            comment.id: comment.body[:MAX_COMMENT_PREVIEW]
            for comment in db.scalars(
                select(CloudShareComment).where(CloudShareComment.id.in_(comment_ids))
            )
        }
        if comment_ids
        else {}
    )

    items: list[dict[str, object]] = []
    for row in rows:
        share = shares[row.share_id]
        item: dict[str, object] = {
            "id": row.id,
            "kind": row.kind,
            "read_at": row.read_at.isoformat() if row.read_at else None,
            "created_at": row.created_at.isoformat(),
            "actor": public_user(actors[row.actor_id]),
            "share": {"id": share.id, "title": share.title, "kind": share.kind},
        }
        if row.kind == "comment":
            item["comment_preview"] = previews.get(row.comment_id, "")
        items.append(item)
    return items
