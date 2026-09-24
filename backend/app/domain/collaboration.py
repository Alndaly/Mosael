"""Unified workspace collaboration seam.

Product modules publish immutable activity here; comments, mentions and reviews use the same
workspace/subject identity. Notifications remain delivery, never the source of collaboration truth.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import (
    ActivityEvent,
    Asset,
    Board,
    Comment,
    CommentMention,
    Sequence,
    User,
    Workflow,
    WorkspaceMember,
)
from app.domain.notifications import notify


class CollaborationError(LocalizedError, ValueError):
    """协作(评论)说不行。带文案 key(`collabErr_*`)。"""


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
        raise CollaborationError("collabErr_unknownSubjectType", kind=subject_type)
    subject = db.get(model, subject_id)
    if subject is None or subject.workspace_id != workspace_id:
        raise CollaborationError("collabErr_subjectNotFound")
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
        raise CollaborationError("collabErr_commentEmpty")
    if len(cleaned) > 5000:
        raise CollaborationError("collabErr_commentTooLong")
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
        raise CommentOwnershipError("collabErr_moveOwnOnly")
    if comment.subject_type != "board":
        raise CollaborationError("collabErr_moveCanvasOnly")
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


def edit_comment(
    db: Session, comment: Comment, *, actor_id: str, body: str,
    body_document: dict[str, Any], mentioned_user_ids: list[str],
) -> Comment:
    if comment.author_id != actor_id:
        raise CommentOwnershipError("collabErr_editOwnOnly")
    cleaned = body.strip()
    if not cleaned or len(cleaned) > 5000:
        raise CollaborationError("collabErr_commentLength")
    if body_document and (body_document.get("type") != "doc" or not isinstance(body_document.get("content"), list)):
        raise CollaborationError("collabErr_commentMalformed")
    previous = list(db.scalars(select(CommentMention).where(CommentMention.comment_id == comment.id)))
    previous_ids = {mention.user_id for mention in previous}
    mentioned = _mentioned_members(db, comment.workspace_id, cleaned, mentioned_user_ids)
    next_ids = {user.id for user in mentioned}
    for mention in previous:
        if mention.user_id not in next_ids:
            db.delete(mention)
    for user in mentioned:
        if user.id in previous_ids:
            continue
        db.add(CommentMention(comment_id=comment.id, user_id=user.id))
        if user.id != actor_id:
            notify(db, comment.workspace_id, type="team", title="你在评论中被提及", body=cleaned[:240],
                   payload={"comment_id": comment.id, "subject_type": comment.subject_type, "subject_id": comment.subject_id},
                   user_id=user.id)
    comment.body = cleaned
    comment.body_document = body_document
    record_activity(db, workspace_id=comment.workspace_id, actor_id=actor_id, action="comment.edited",
                    subject_type=comment.subject_type, subject_id=comment.subject_id, summary="编辑了评论",
                    payload={"comment_id": comment.id, "mentioned_user_ids": sorted(next_ids)})
    db.flush()
    return comment


def delete_comment(db: Session, comment: Comment, *, actor_id: str) -> None:
    """Delete an author's own comment while retaining an immutable audit event."""
    if comment.author_id != actor_id:
        raise CommentOwnershipError("collabErr_deleteOwnOnly")
    for mention in db.scalars(
        select(CommentMention).where(CommentMention.comment_id == comment.id)
    ):
        db.delete(mention)
    record_activity(
        db,
        workspace_id=comment.workspace_id,
        actor_id=actor_id,
        action="comment.deleted",
        subject_type=comment.subject_type,
        subject_id=comment.subject_id,
        summary="删除了评论",
        payload={"comment_id": comment.id},
    )
    db.delete(comment)
    db.flush()


