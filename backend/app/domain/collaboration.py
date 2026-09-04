"""Unified workspace collaboration seam.

Product modules publish immutable activity here; comments, mentions and reviews use the same
workspace/subject identity. Notifications remain delivery, never the source of collaboration truth.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, aliased

from app.db.models import (
    ActivityEvent,
    Asset,
    Board,
    Comment,
    CommentMention,
    Review,
    Sequence,
    User,
    Workflow,
    WorkspaceMember,
    now,
)
from app.domain.notifications import notify


class CollaborationError(ValueError):
    pass


class CommentOwnershipError(CollaborationError):
    pass


SUBJECT_MODELS = {
    "board": Board,
    "workflow": Workflow,
    "sequence": Sequence,
    "asset": Asset,
}
REVIEW_STATUSES = ("pending", "approved", "changes_requested", "cancelled")
_MENTION = re.compile(r"(?<![\w@])@([\w.\-]{2,80})", re.UNICODE)


def ensure_subject(db: Session, workspace_id: str, subject_type: str, subject_id: str) -> Any:
    model = SUBJECT_MODELS.get(subject_type)
    if model is None:
        raise CollaborationError(f"不支持的协作对象类型:{subject_type}")
    subject = db.get(model, subject_id)
    if subject is None or subject.workspace_id != workspace_id:
        raise CollaborationError("协作对象不存在")
    return subject


def record_activity(
    db: Session,
    *,
    workspace_id: str,
    actor_id: str | None,
    action: str,
    subject_type: str,
    subject_id: str,
    summary: str,
    payload: dict[str, Any] | None = None,
    source_type: str | None = None,
    source_id: str | None = None,
) -> ActivityEvent:
    event = ActivityEvent(
        workspace_id=workspace_id,
        actor_id=actor_id,
        action=action,
        subject_type=subject_type,
        subject_id=subject_id,
        summary=summary.strip()[:240],
        payload=payload or {},
        source_type=source_type,
        source_id=source_id,
    )
    db.add(event)
    return event


def _actor(user: User | None, actor_id: str | None) -> dict[str, Any] | None:
    if user is None and actor_id is None:
        return None
    return {
        "id": actor_id,
        "username": user.username if user else "",
        "display_name": user.display_name if user else "",
        "avatar_key": user.avatar_key if user else "",
    }


def list_activity(
    db: Session,
    workspace_id: str,
    *,
    subject_type: str | None = None,
    subject_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    stmt = (
        select(ActivityEvent, User)
        .outerjoin(User, User.id == ActivityEvent.actor_id)
        .where(ActivityEvent.workspace_id == workspace_id)
    )
    if subject_type:
        stmt = stmt.where(ActivityEvent.subject_type == subject_type)
    if subject_id:
        stmt = stmt.where(ActivityEvent.subject_id == subject_id)
    rows = db.execute(stmt.order_by(ActivityEvent.created_at.desc()).limit(min(max(limit, 1), 100))).all()
    return [
        {
            "id": event.id,
            "workspace_id": event.workspace_id,
            "actor_id": event.actor_id,
            "actor": _actor(user, event.actor_id),
            "action": event.action,
            "subject_type": event.subject_type,
            "subject_id": event.subject_id,
            "summary": event.summary,
            "payload": event.payload or {},
            "created_at": event.created_at,
        }
        for event, user in rows
    ]


def _mentioned_members(
    db: Session, workspace_id: str, body: str, explicit_ids: list[str]
) -> list[User]:
    members = list(
        db.execute(
            select(User)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == workspace_id)
        ).scalars()
    )
    wanted_ids = {str(one) for one in explicit_ids if one}
    wanted_names = {match.group(1) for match in _MENTION.finditer(body)}
    return [user for user in members if user.id in wanted_ids or user.username in wanted_names]


def create_comment(
    db: Session,
    *,
    workspace_id: str,
    subject_type: str,
    subject_id: str,
    author_id: str,
    body: str,
    mentioned_user_ids: list[str] | None = None,
    anchor: dict[str, Any] | None = None,
    body_document: dict[str, Any] | None = None,
) -> Comment:
    ensure_subject(db, workspace_id, subject_type, subject_id)
    cleaned = body.strip()
    if not cleaned:
        raise CollaborationError("评论不能为空")
    if len(cleaned) > 5000:
        raise CollaborationError("评论最多 5000 字")
    comment = Comment(
        workspace_id=workspace_id,
        subject_type=subject_type,
        subject_id=subject_id,
        author_id=author_id,
        body=cleaned,
        anchor=anchor or {},
        body_document=body_document or {},
    )
    db.add(comment)
    db.flush()
    mentioned = _mentioned_members(db, workspace_id, cleaned, mentioned_user_ids or [])
    for user in mentioned:
        db.add(CommentMention(comment_id=comment.id, user_id=user.id))
        if user.id != author_id:
            notify(
                db,
                workspace_id,
                type="team",
                title="你在评论中被提及",
                body=cleaned[:240],
                payload={"comment_id": comment.id, "subject_type": subject_type, "subject_id": subject_id},
                user_id=user.id,
            )
    record_activity(
        db,
        workspace_id=workspace_id,
        actor_id=author_id,
        action="comment.created",
        subject_type=subject_type,
        subject_id=subject_id,
        summary="发表了评论",
        payload={
            "comment_id": comment.id,
            "mentioned_user_ids": [user.id for user in mentioned],
            **({"anchor": comment.anchor} if comment.anchor else {}),
        },
    )
    return comment


def list_comments(db: Session, workspace_id: str, subject_type: str, subject_id: str) -> list[dict[str, Any]]:
    ensure_subject(db, workspace_id, subject_type, subject_id)
    rows = db.execute(
        select(Comment, User)
        .outerjoin(User, User.id == Comment.author_id)
        .where(
            Comment.workspace_id == workspace_id,
            Comment.subject_type == subject_type,
            Comment.subject_id == subject_id,
        )
        .order_by(Comment.created_at.asc())
    ).all()
    mentions: dict[str, list[str]] = {}
    comment_ids = [comment.id for comment, _ in rows]
    if comment_ids:
        for comment_id, user_id in db.execute(
            select(CommentMention.comment_id, CommentMention.user_id).where(CommentMention.comment_id.in_(comment_ids))
        ):
            mentions.setdefault(comment_id, []).append(user_id)
    return [
        {
            "id": comment.id,
            "workspace_id": comment.workspace_id,
            "subject_type": comment.subject_type,
            "subject_id": comment.subject_id,
            "author_id": comment.author_id,
            "author": _actor(user, comment.author_id),
            "body": comment.body,
            "mentioned_user_ids": mentions.get(comment.id, []),
            "anchor": comment.anchor or None,
            "body_document": comment.body_document or {},
            "created_at": comment.created_at,
            "updated_at": comment.updated_at,
        }
        for comment, user in rows
    ]


def move_comment(
    db: Session,
    comment: Comment,
    *,
    actor_id: str,
    anchor: dict[str, Any],
) -> Comment:
    """Move a spatial comment without turning it into board content.

    A comment's author owns its placement. Workspace editors may read the same discussion, but
    cannot rearrange somebody else's canvas annotations.
    """
    if comment.author_id != actor_id:
        raise CommentOwnershipError("只能移动自己发布的评论")
    if comment.subject_type != "board":
        raise CollaborationError("只有画布评论支持移动")
    comment.anchor = anchor
    record_activity(
        db,
        workspace_id=comment.workspace_id,
        actor_id=actor_id,
        action="comment.moved",
        subject_type=comment.subject_type,
        subject_id=comment.subject_id,
        summary="移动了评论",
        payload={"comment_id": comment.id, "anchor": anchor},
    )
    db.flush()
    return comment


def request_review(
    db: Session,
    *,
    workspace_id: str,
    subject_type: str,
    subject_id: str,
    requested_by: str,
    reviewer_id: str,
    note: str = "",
) -> Review:
    ensure_subject(db, workspace_id, subject_type, subject_id)
    member = db.scalar(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == reviewer_id,
        )
    )
    if member is None:
        raise CollaborationError("审阅人不是该工作区成员")
    review = Review(
        workspace_id=workspace_id,
        subject_type=subject_type,
        subject_id=subject_id,
        requested_by=requested_by,
        reviewer_id=reviewer_id,
        note=note.strip()[:2000],
    )
    db.add(review)
    db.flush()
    notify(
        db,
        workspace_id,
        type="team",
        title="有新的审阅请求",
        body=review.note,
        payload={"review_id": review.id, "subject_type": subject_type, "subject_id": subject_id},
        user_id=reviewer_id,
    )
    record_activity(
        db,
        workspace_id=workspace_id,
        actor_id=requested_by,
        action="review.requested",
        subject_type=subject_type,
        subject_id=subject_id,
        summary="发起了审阅",
        payload={"review_id": review.id, "reviewer_id": reviewer_id},
    )
    return review


def decide_review(
    db: Session, review: Review, *, actor_id: str, status: str, note: str = ""
) -> Review:
    if status not in ("approved", "changes_requested", "cancelled"):
        raise CollaborationError("审阅决定不合法")
    if review.status != "pending":
        raise CollaborationError("这项审阅已经结束")
    if status == "cancelled":
        if actor_id != review.requested_by:
            raise CollaborationError("只有发起人可以取消审阅")
    elif actor_id != review.reviewer_id:
        raise CollaborationError("只有指定审阅人可以作出决定")
    review.status = status
    review.decision_note = note.strip()[:2000]
    review.decided_by = actor_id
    review.decided_at = now()
    record_activity(
        db,
        workspace_id=review.workspace_id,
        actor_id=actor_id,
        action=f"review.{status}",
        subject_type=review.subject_type,
        subject_id=review.subject_id,
        summary={
            "approved": "通过了审阅",
            "changes_requested": "要求修改",
            "cancelled": "取消了审阅",
        }[status],
        payload={"review_id": review.id},
    )
    target = review.requested_by
    if target and target != actor_id:
        notify(
            db,
            review.workspace_id,
            type="team",
            title="审阅已有结果",
            body=review.decision_note,
            payload={"review_id": review.id, "status": status},
            user_id=target,
        )
    return review


def list_reviews(db: Session, workspace_id: str, subject_type: str, subject_id: str) -> list[dict[str, Any]]:
    ensure_subject(db, workspace_id, subject_type, subject_id)
    reviewer_user = aliased(User)
    requester_user = aliased(User)
    rows = db.execute(
        select(Review, reviewer_user, requester_user)
        .outerjoin(reviewer_user, reviewer_user.id == Review.reviewer_id)
        .outerjoin(requester_user, requester_user.id == Review.requested_by)
        .where(
            Review.workspace_id == workspace_id,
            Review.subject_type == subject_type,
            Review.subject_id == subject_id,
        )
        .order_by(Review.created_at.desc())
    ).all()
    result: list[dict[str, Any]] = []
    for review, reviewer, requester in rows:
        result.append(
            {
                "id": review.id,
                "workspace_id": review.workspace_id,
                "subject_type": review.subject_type,
                "subject_id": review.subject_id,
                "requested_by": review.requested_by,
                "requester": _actor(requester, review.requested_by),
                "reviewer_id": review.reviewer_id,
                "reviewer": _actor(reviewer, review.reviewer_id),
                "status": review.status,
                "note": review.note,
                "decision_note": review.decision_note,
                "decided_by": review.decided_by,
                "created_at": review.created_at,
                "decided_at": review.decided_at,
            }
        )
    return result
