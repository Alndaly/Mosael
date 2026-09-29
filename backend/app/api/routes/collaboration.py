from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas.collaboration import (
    ActivityOut,
    CommentAnchorUpdate,
    CommentCreate,
    CommentContentUpdate,
    CommentOut,
)
from app.domain.collaboration import CollaborationError, CommentOwnershipError
from app.domain.collaboration import use_cases as collaboration

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
    return collaboration.list_activity(
        db, user, workspace_id, subject_type=subject_type, subject_id=subject_id, limit=limit
    )


@router.get("/comments", response_model=list[CommentOut])
def comments(
    workspace_id: str,
    subject_type: str,
    subject_id: str,
    db: DbSession,
    user: CurrentUser,
) -> list[dict]:
    try:
        return collaboration.list_comments(db, user, workspace_id, subject_type, subject_id)
    except CollaborationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/comments", response_model=CommentOut)
def add_comment(body: CommentCreate, db: Tx, user: CurrentUser) -> dict:
    try:
        return collaboration.create_comment(
            db,
            user,
            body.workspace_id,
            subject_type=body.subject_type,
            subject_id=body.subject_id,
            body=body.body,
            mentioned_user_ids=body.mentioned_user_ids,
            anchor=body.anchor.model_dump(exclude_none=True) if body.anchor else None,
            body_document=body.body_document,
        )
    except CollaborationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/comments/{comment_id}", response_model=CommentOut)
def update_comment_anchor(comment_id: str, body: CommentAnchorUpdate, db: Tx, user: CurrentUser) -> dict:
    try:
        return collaboration.move_comment(
            db, user, body.workspace_id, comment_id, body.anchor.model_dump(exclude_none=True)
        )
    except CommentOwnershipError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CollaborationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/comments/{comment_id}/content", response_model=CommentOut)
def update_comment_content(comment_id: str, body: CommentContentUpdate, db: Tx, user: CurrentUser) -> dict:
    try:
        return collaboration.edit_comment(
            db,
            user,
            body.workspace_id,
            comment_id,
            body=body.body,
            body_document=body.body_document,
            mentioned_user_ids=body.mentioned_user_ids,
        )
    except CommentOwnershipError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except CollaborationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/comments/{comment_id}", status_code=204)
def remove_comment(comment_id: str, workspace_id: str, db: Tx, user: CurrentUser) -> Response:
    try:
        collaboration.delete_comment(db, user, workspace_id, comment_id)
    except CommentOwnershipError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return Response(status_code=204)
