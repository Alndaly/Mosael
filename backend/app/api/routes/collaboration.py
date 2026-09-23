from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CurrentUser, DbSession
from app.api.schemas.collaboration import (
    ActivityOut,
    CommentAnchorUpdate,
    CommentCreate,
    CommentContentUpdate,
    CommentOut,
)
from app.db.models import Comment
from app.domain.collaboration import (
    CollaborationError,
    CommentOwnershipError,
    create_comment,
    delete_comment,
    edit_comment,
    list_activity,
    list_comments,
    move_comment,
)
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm

router = APIRouter(tags=["collaboration"])


@router.get("/activity", response_model=list[ActivityOut])
def activity(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    subject_type: str | None = None,
    subject_id: str | None = None,
    limit: int = 50,
) -> list[dict]:
    ensure_workspace_access(db, user, workspace_id)
    return list_activity(
        db, workspace_id, subject_type=subject_type, subject_id=subject_id, limit=limit
    )


@router.get("/comments", response_model=list[CommentOut])
def comments(
    workspace_id: str,
    subject_type: str,
    subject_id: str,
    db: DbSession,
    user: CurrentUser,
) -> list[dict]:
    ensure_workspace_access(db, user, workspace_id)
    try:
        return list_comments(db, workspace_id, subject_type, subject_id)
    except CollaborationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/comments", response_model=CommentOut)
def add_comment(body: CommentCreate, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    try:
        comment = create_comment(
            db,
            workspace_id=body.workspace_id,
            subject_type=body.subject_type,
            subject_id=body.subject_id,
            author_id=user.id,
            body=body.body,
            mentioned_user_ids=body.mentioned_user_ids,
            anchor=body.anchor.model_dump(exclude_none=True) if body.anchor else None,
            body_document=body.body_document,
        )
        comment_id = comment.id
        db.commit()
        return next(
            one
            for one in list_comments(db, body.workspace_id, body.subject_type, body.subject_id)
            if one["id"] == comment_id
        )
    except CollaborationError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/comments/{comment_id}", response_model=CommentOut)
def update_comment_anchor(comment_id: str, body: CommentAnchorUpdate, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    comment = db.get(Comment, comment_id)
    if comment is None or comment.workspace_id != body.workspace_id:
        raise HTTPException(status_code=404, detail="评论不存在")
    try:
        move_comment(
            db,
            comment,
            actor_id=user.id,
            anchor=body.anchor.model_dump(exclude_none=True),
        )
        db.commit()
        return next(
            one
            for one in list_comments(db, comment.workspace_id, comment.subject_type, comment.subject_id)
            if one["id"] == comment.id
        )
    except CommentOwnershipError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CollaborationError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/comments/{comment_id}/content", response_model=CommentOut)
def update_comment_content(comment_id: str, body: CommentContentUpdate, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    comment = db.get(Comment, comment_id)
    if comment is None or comment.workspace_id != body.workspace_id:
        raise HTTPException(status_code=404, detail="评论不存在")
    try:
        edit_comment(db, comment, actor_id=user.id, body=body.body,
                     body_document=body.body_document, mentioned_user_ids=body.mentioned_user_ids)
        db.commit()
        return next(one for one in list_comments(db, comment.workspace_id, comment.subject_type, comment.subject_id)
                    if one["id"] == comment.id)
    except CommentOwnershipError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CollaborationError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/comments/{comment_id}", status_code=204)
def remove_comment(comment_id: str, workspace_id: str, db: DbSession, user: CurrentUser) -> Response:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    comment = db.get(Comment, comment_id)
    if comment is None or comment.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="评论不存在")
    try:
        delete_comment(db, comment, actor_id=user.id)
        db.commit()
        return Response(status_code=204)
    except CommentOwnershipError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc


