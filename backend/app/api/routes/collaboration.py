from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser, DbSession
from app.api.schemas.collaboration import (
    ActivityOut,
    CommentCreate,
    CommentOut,
    ReviewCreate,
    ReviewDecision,
    ReviewOut,
)
from app.db.models import Review
from app.domain.collaboration import (
    CollaborationError,
    create_comment,
    decide_review,
    list_activity,
    list_comments,
    list_reviews,
    request_review,
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


@router.get("/reviews", response_model=list[ReviewOut])
def reviews(
    workspace_id: str,
    subject_type: str,
    subject_id: str,
    db: DbSession,
    user: CurrentUser,
) -> list[dict]:
    ensure_workspace_access(db, user, workspace_id)
    try:
        return list_reviews(db, workspace_id, subject_type, subject_id)
    except CollaborationError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/reviews", response_model=ReviewOut)
def add_review(body: ReviewCreate, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    try:
        review = request_review(
            db,
            workspace_id=body.workspace_id,
            subject_type=body.subject_type,
            subject_id=body.subject_id,
            requested_by=user.id,
            reviewer_id=body.reviewer_id,
            note=body.note,
        )
        review_id = review.id
        db.commit()
        return next(one for one in list_reviews(db, body.workspace_id, body.subject_type, body.subject_id) if one["id"] == review_id)
    except CollaborationError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/reviews/{review_id}/decision", response_model=ReviewOut)
def review_decision(review_id: str, body: ReviewDecision, db: DbSession, user: CurrentUser) -> dict:
    review = db.get(Review, review_id)
    if review is None:
        raise HTTPException(status_code=404, detail="审阅不存在")
    # 审阅决定会改变团队可交付状态，必须和创建评论/审阅一样显式声明写权限；
    # “恰好是指定 reviewer”只回答谁能决定，不替代工作区授权。
    ensure_workspace_perm(db, user, review.workspace_id, "edit")
    try:
        decide_review(db, review, actor_id=user.id, status=body.status, note=body.note)
        workspace_id, subject_type, subject_id = review.workspace_id, review.subject_type, review.subject_id
        db.commit()
        return next(one for one in list_reviews(db, workspace_id, subject_type, subject_id) if one["id"] == review_id)
    except CollaborationError as exc:
        db.rollback()
        raise HTTPException(status_code=403, detail=str(exc)) from exc
