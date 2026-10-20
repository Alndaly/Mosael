"""社区分享 + 互动(点赞 / 收藏 / 评论)的业务规则。

服务端对 `payload` 只做两件事:**确认它是一份 JSON**(请求体解析已经保证了这一点)和
**量它的紧凑 UTF-8 字节数**(上限 2 MB)。节点、画板、版本号这些内容一概不解析。

公开读接口返回的每一项都只带作者的三列公开身份(`display_name` / `handle` / `avatar_seed`),
**不认识 email**。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import and_, delete, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from cloud.domain.identity import ensure_identity, public_user
from cloud.errors import CloudError
from cloud.models import (
    CloudShare,
    CloudShareComment,
    CloudShareFavorite,
    CloudShareLike,
    CloudUser,
    now,
)
from cloud.pagination import after_clause, clamp_limit, decode_cursor, encode_cursor

SHARE_KINDS = ("workflow", "board")
SHARE_STATUS_LISTED = "listed"
SHARE_STATUS_REMOVED = "removed"
SHARE_SORTS = ("new", "hot")

MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_TITLE = 200
MAX_SUMMARY = 500
MAX_LICENSE = 64
MAX_COMMENT = 2000

#: 给人看的 2 MB。413 的文案用这个,不让用户去换算 2097152。
HUMAN_PAYLOAD_LIMIT = "2 MB"


def payload_bytes(payload: Any) -> int:
    """按紧凑 UTF-8 JSON 算实际字节数 —— 和存进 JSONB 的那份内容同一个尺度。"""
    try:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CloudError(422, "invalid_payload") from exc
    return len(encoded.encode("utf-8"))


def _clean_title(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise CloudError(422, "title_required")
    if len(value) > MAX_TITLE:
        raise CloudError(422, "title_too_long", max=MAX_TITLE)
    return value


def _clean_summary(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if len(value) > MAX_SUMMARY:
        raise CloudError(422, "summary_too_long", max=MAX_SUMMARY)
    return value


def _clean_license(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if len(value) > MAX_LICENSE:
        raise CloudError(422, "license_too_long", max=MAX_LICENSE)
    return value


def require_listed_share(db: Session, share_id: str) -> CloudShare:
    """按公开 id 取一次还在架上的分享。不存在 / 已被作者删掉都是一种回答:404。"""
    share = db.get(CloudShare, share_id)
    if share is None or share.status != SHARE_STATUS_LISTED:
        raise CloudError(404, "share_not_found")
    return share


# ---------------------------------------------------------------- 发布 / 详情


def create_share(
    db: Session,
    user: CloudUser,
    *,
    kind: str,
    title: str,
    summary: str | None,
    payload: Any,
    license: str | None,
) -> dict[str, object]:
    """发布。**需要 session + 已设置的 display_name**;没有名字是 409。"""
    ensure_identity(user)
    if kind not in SHARE_KINDS:
        raise CloudError(422, "invalid_kind", allowed=" / ".join(SHARE_KINDS))
    if payload is None:
        raise CloudError(422, "invalid_payload")
    size = payload_bytes(payload)
    if size > MAX_PAYLOAD_BYTES:
        # 超限直接拒绝 —— 不截断、不存半个工程文件。
        raise CloudError(413, "payload_too_large", limit=HUMAN_PAYLOAD_LIMIT)

    share = CloudShare(
        owner_user_id=user.id,
        kind=kind,
        title=_clean_title(title),
        summary=_clean_summary(summary),
        payload=payload,
        bytes=size,
        license=_clean_license(license),
        status=SHARE_STATUS_LISTED,
        downloads=0,
    )
    db.add(share)
    db.commit()
    return _serialize_many(db, [share], user)[0]


def get_share(db: Session, viewer: CloudUser | None, share_id: str) -> dict[str, object]:
    """详情。**不带 payload** —— 内容只在 `/payload` 与 `/download` 出。"""
    share = require_listed_share(db, share_id)
    return _serialize_many(db, [share], viewer)[0]


def get_share_payload(db: Session, share_id: str) -> Any:
    return require_listed_share(db, share_id).payload


def record_download(db: Session, share_id: str) -> Any:
    """公开下载:计数 +1 并把工程文件交出去。用一条 UPDATE 自增,避免读改写丢计数。"""
    result = db.execute(
        update(CloudShare)
        .where(CloudShare.id == share_id, CloudShare.status == SHARE_STATUS_LISTED)
        .values(downloads=CloudShare.downloads + 1)
    )
    if result.rowcount == 0:
        db.rollback()
        raise CloudError(404, "share_not_found")
    db.commit()
    return get_share_payload(db, share_id)


def delete_share(db: Session, user: CloudUser, share_id: str) -> None:
    """作者删自己的分享 = 软删(`status='removed'`)。

    **不是作者一律 404**:响应不区分"没有这个 id"与"这个 id 不是你的",别人试不出某个
    已删除的分享曾经存在。作者重复删除仍回 204(幂等)。
    """
    share = db.get(CloudShare, share_id)
    if share is None or share.owner_user_id != user.id:
        raise CloudError(404, "share_not_found")
    if share.status != SHARE_STATUS_REMOVED:
        share.status = SHARE_STATUS_REMOVED
        share.updated_at = now()
        db.commit()


# ---------------------------------------------------------------- 列表 / 分页


def list_shares(
    db: Session,
    viewer: CloudUser | None,
    *,
    q: str = "",
    kind: str = "",
    sort: str = "new",
    limit: int | None = None,
    cursor: str = "",
    owner_user_id: str | None = None,
) -> tuple[list[dict[str, object]], str | None]:
    """公开列表。`sort=new` 按创建时间;`sort=hot` 按互动热度(下载 + 点赞×3 + 收藏×2 + 评论)。"""
    if kind and kind not in SHARE_KINDS:
        raise CloudError(422, "invalid_kind", allowed=" / ".join(SHARE_KINDS))
    if sort not in SHARE_SORTS:
        raise CloudError(422, "invalid_sort", allowed=" / ".join(SHARE_SORTS))

    size = clamp_limit(limit)
    conditions = [CloudShare.status == SHARE_STATUS_LISTED]
    if owner_user_id is not None:
        conditions.append(CloudShare.owner_user_id == owner_user_id)
    if kind:
        conditions.append(CloudShare.kind == kind)
    needle = (q or "").strip()
    if needle:
        conditions.append(
            or_(
                CloudShare.title.icontains(needle, autoescape=True),
                CloudShare.summary.icontains(needle, autoescape=True),
            )
        )
    if sort == "hot":
        return _list_hot(db, viewer, conditions, size, cursor)
    return _list_new(db, viewer, conditions, size, cursor)


def _list_new(db: Session, viewer, conditions, size: int, cursor: str):
    stmt = select(CloudShare).where(*conditions)
    after = decode_cursor(cursor, 2)
    if after is not None:
        stmt = stmt.where(after_clause([CloudShare.created_at, CloudShare.id], after))
    rows = list(db.scalars(stmt.order_by(CloudShare.created_at.desc(), CloudShare.id.desc()).limit(size + 1)))
    next_cursor = (
        encode_cursor([rows[size - 1].created_at, rows[size - 1].id]) if len(rows) > size else None
    )
    page = rows[:size]
    return _serialize_many(db, page, viewer), next_cursor


def _list_hot(db: Session, viewer, conditions, size: int, cursor: str):
    likes = (
        select(func.count())
        .select_from(CloudShareLike)
        .where(CloudShareLike.share_id == CloudShare.id)
        .correlate(CloudShare)
        .scalar_subquery()
    )
    favorites = (
        select(func.count())
        .select_from(CloudShareFavorite)
        .where(CloudShareFavorite.share_id == CloudShare.id)
        .correlate(CloudShare)
        .scalar_subquery()
    )
    comments = (
        select(func.count())
        .select_from(CloudShareComment)
        .where(CloudShareComment.share_id == CloudShare.id)
        .correlate(CloudShare)
        .scalar_subquery()
    )
    hot = CloudShare.downloads + 3 * likes + 2 * favorites + comments
    stmt = select(CloudShare.id, CloudShare.created_at, hot.label("hot_score")).where(*conditions)

    after = decode_cursor(cursor, 3)
    if after is not None:
        stmt = stmt.where(
            or_(
                hot < after[0],
                and_(*[hot == after[0], CloudShare.created_at < after[1]]),
                and_(*[hot == after[0], CloudShare.created_at == after[1], CloudShare.id < after[2]]),
            )
        )
    found = db.execute(
        stmt.order_by(hot.desc(), CloudShare.created_at.desc(), CloudShare.id.desc()).limit(size + 1)
    ).all()
    next_cursor = (
        encode_cursor([found[size - 1][2], found[size - 1][1], found[size - 1][0]])
        if len(found) > size
        else None
    )
    ids = [row[0] for row in found[:size]]
    shares = _shares_by_ids(db, ids)
    return _serialize_many(db, shares, viewer), next_cursor


def list_user_shares(
    db: Session,
    viewer: CloudUser | None,
    handle: str,
    *,
    limit: int | None = None,
    cursor: str = "",
) -> tuple[list[dict[str, object]], str | None]:
    normalized = (handle or "").strip().lower()
    owner = db.scalar(select(CloudUser).where(CloudUser.handle == normalized)) if normalized else None
    if owner is None:
        raise CloudError(404, "user_not_found")
    return list_shares(db, viewer, limit=limit, cursor=cursor, owner_user_id=owner.id)


# ---------------------------------------------------------------- 序列化 / 统计


def _shares_by_ids(db: Session, ids: list[str]) -> list[CloudShare]:
    if not ids:
        return []
    found = {share.id: share for share in db.scalars(select(CloudShare).where(CloudShare.id.in_(ids)))}
    return [found[share_id] for share_id in ids if share_id in found]


def _serialize_many(db: Session, shares: list[CloudShare], viewer: CloudUser | None) -> list[dict[str, object]]:
    if not shares:
        return []
    ids = [share.id for share in shares]
    stats = {
        share.id: {"downloads": share.downloads, "likes": 0, "favorites": 0, "comments": 0}
        for share in shares
    }
    for model, key in (
        (CloudShareLike, "likes"),
        (CloudShareFavorite, "favorites"),
        (CloudShareComment, "comments"),
    ):
        for share_id, total in db.execute(
            select(model.share_id, func.count()).where(model.share_id.in_(ids)).group_by(model.share_id)
        ):
            stats[share_id][key] = total

    authors = {
        user.id: user
        for user in db.scalars(select(CloudUser).where(CloudUser.id.in_({share.owner_user_id for share in shares})))
    }
    liked: set[str] = set()
    favorited: set[str] = set()
    if viewer is not None:
        liked = set(
            db.scalars(
                select(CloudShareLike.share_id).where(
                    CloudShareLike.user_id == viewer.id, CloudShareLike.share_id.in_(ids)
                )
            )
        )
        favorited = set(
            db.scalars(
                select(CloudShareFavorite.share_id).where(
                    CloudShareFavorite.user_id == viewer.id, CloudShareFavorite.share_id.in_(ids)
                )
            )
        )

    return [
        {
            "id": share.id,
            "kind": share.kind,
            "title": share.title,
            "summary": share.summary,
            "bytes": share.bytes,
            "license": share.license,
            "created_at": share.created_at.isoformat(),
            "author": public_user(authors[share.owner_user_id]),
            "stats": stats[share.id],
            "liked_by_me": share.id in liked,
            "favorited_by_me": share.id in favorited,
        }
        for share in shares
    ]


# ---------------------------------------------------------------- 互动


def like_share(db: Session, user: CloudUser, share_id: str, *, liked: bool) -> None:
    """点赞。**靠主键唯一约束去重**:重复 POST 撞 IntegrityError 就当成功(204),不是 409。"""
    require_listed_share(db, share_id)
    _toggle(db, CloudShareLike, share_id, user.id, wanted=liked)


def favorite_share(db: Session, user: CloudUser, share_id: str, *, favorited: bool) -> None:
    require_listed_share(db, share_id)
    _toggle(db, CloudShareFavorite, share_id, user.id, wanted=favorited)


def _toggle(db: Session, model, share_id: str, user_id: str, *, wanted: bool) -> None:
    if wanted:
        try:
            db.execute(insert(model).values(share_id=share_id, user_id=user_id, created_at=now()))
            db.commit()
        except IntegrityError:
            # 已经点过了 —— 唯一约束给出的正是幂等:第二次不改变任何东西。
            db.rollback()
        return
    db.execute(delete(model).where(model.share_id == share_id, model.user_id == user_id))
    db.commit()


# ---------------------------------------------------------------- 评论


def add_comment(db: Session, user: CloudUser, share_id: str, body: str) -> dict[str, object]:
    """评论。需要 session + display_name;空评论 422;**存原文**,不做 HTML / markdown 处理。"""
    ensure_identity(user)
    require_listed_share(db, share_id)
    if not body.strip():
        raise CloudError(422, "comment_empty")
    if len(body) > MAX_COMMENT:
        raise CloudError(422, "comment_too_long", max=MAX_COMMENT)
    comment = CloudShareComment(share_id=share_id, user_id=user.id, body=body)
    db.add(comment)
    db.commit()
    return _comment_out(comment, user)


def list_comments(
    db: Session,
    share_id: str,
    *,
    limit: int | None = None,
    cursor: str = "",
) -> tuple[list[dict[str, object]], str | None]:
    """评论列表,新的在前。作者只给公开三列。"""
    require_listed_share(db, share_id)
    size = clamp_limit(limit)
    stmt = select(CloudShareComment).where(CloudShareComment.share_id == share_id)
    after = decode_cursor(cursor, 2)
    if after is not None:
        stmt = stmt.where(after_clause([CloudShareComment.created_at, CloudShareComment.id], after))
    rows = list(
        db.scalars(
            stmt.order_by(CloudShareComment.created_at.desc(), CloudShareComment.id.desc()).limit(size + 1)
        )
    )
    next_cursor = (
        encode_cursor([rows[size - 1].created_at, rows[size - 1].id]) if len(rows) > size else None
    )
    page = rows[:size]
    authors = {
        user.id: user
        for user in db.scalars(select(CloudUser).where(CloudUser.id.in_({comment.user_id for comment in page})))
    }
    return [_comment_out(comment, authors[comment.user_id]) for comment in page], next_cursor


def delete_comment(db: Session, user: CloudUser, share_id: str, comment_id: str) -> None:
    """只有评论本人能删;别人的评论一律 404(不给出"存在但不是你的"这个区别)。"""
    comment = db.get(CloudShareComment, comment_id)
    if comment is None or comment.share_id != share_id or comment.user_id != user.id:
        raise CloudError(404, "comment_not_found")
    db.delete(comment)
    db.commit()


def _comment_out(comment: CloudShareComment, author: CloudUser) -> dict[str, object]:
    return {
        "id": comment.id,
        "share_id": comment.share_id,
        "body": comment.body,
        "created_at": comment.created_at.isoformat(),
        "author": public_user(author),
    }
