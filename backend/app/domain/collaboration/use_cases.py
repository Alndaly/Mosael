"""活动流与评论的用例:按工作区过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看活动流和评论不点名权限;发、移、改、删评论点名 edit(只能动自己的,那条判据在领域函数里)。
不提交事务。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Comment, User
from app.domain import collaboration as ops
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm


def editable_comment(db: Session, user: User, workspace_id: str, comment_id: str) -> Comment:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    comment = db.get(Comment, comment_id)
    if comment is None or comment.workspace_id != workspace_id:
        raise NotVisible("routeErr_commentNotFound")
    return comment


def _listed(db: Session, comment: Comment) -> dict[str, Any]:
    """评论在列表里的那副样子(带作者和提及)。会话不自动 flush,先把刚加的提及落下去再查。"""
    db.flush()
    return next(
        one
        for one in ops.list_comments(db, comment.workspace_id, comment.subject_type, comment.subject_id)
        if one["id"] == comment.id
    )


# ---------------- 读 ----------------


def list_activity(
    db: Session,
    user: User,
    workspace_id: str,
    *,
    subject_type: str | None = None,
    subject_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    ensure_workspace_access(db, user, workspace_id)
    return ops.list_activity(db, workspace_id, subject_type=subject_type, subject_id=subject_id, limit=limit)


def list_comments(db: Session, user: User, workspace_id: str, subject_type: str, subject_id: str) -> list[dict[str, Any]]:
    ensure_workspace_access(db, user, workspace_id)
    return ops.list_comments(db, workspace_id, subject_type, subject_id)


# ---------------- 写 ----------------


def create_comment(db: Session, user: User, workspace_id: str, **fields: Any) -> dict[str, Any]:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    comment = ops.create_comment(db, workspace_id=workspace_id, author_id=user.id, **fields)
    return _listed(db, comment)


def move_comment(db: Session, user: User, workspace_id: str, comment_id: str, anchor: dict[str, Any]) -> dict[str, Any]:
    comment = editable_comment(db, user, workspace_id, comment_id)
    ops.move_comment(db, comment, actor_id=user.id, anchor=anchor)
    return _listed(db, comment)


def edit_comment(
    db: Session,
    user: User,
    workspace_id: str,
    comment_id: str,
    *,
    body: str,
    body_document: dict[str, Any],
    mentioned_user_ids: list[str],
) -> dict[str, Any]:
    comment = editable_comment(db, user, workspace_id, comment_id)
    ops.edit_comment(
        db, comment, actor_id=user.id, body=body, body_document=body_document, mentioned_user_ids=mentioned_user_ids
    )
    return _listed(db, comment)


def delete_comment(db: Session, user: User, workspace_id: str, comment_id: str) -> None:
    ops.delete_comment(db, editable_comment(db, user, workspace_id, comment_id), actor_id=user.id)
