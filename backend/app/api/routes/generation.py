from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import delete, select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    GenerationCreate,
    GenerationCreateResponse,
    GenerationJobOut,
    GenerationModelOut,
    GenerationSessionCreate,
    GenerationSessionOut,
    GenerationSessionUpdate,
)
from app.core.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import GenerationJob, GenerationModel, GenerationSession, Job, now
from app.domain.generation import create_generation_job, ensure_builtin_generation_models
from app.domain.generation.operations import GenerationDomainError
from app.domain.generation.runner import start_generation_thread

router = APIRouter(tags=["generation"])


@router.post("/generation/sessions", response_model=GenerationSessionOut)
def create_generation_session(
    body: GenerationSessionCreate, db: DbSession, user: CurrentUser
) -> GenerationSession:
    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    title = body.title.strip() or "新生成"
    session = GenerationSession(workspace_id=body.workspace_id, title=title)
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.get("/generation/sessions", response_model=list[GenerationSessionOut])
def list_generation_sessions(workspace_id: str, db: DbSession, user: CurrentUser) -> list[GenerationSession]:
    ensure_workspace_access(db, user, workspace_id)
    _attach_legacy_generations(db, workspace_id)
    stmt = (
        select(GenerationSession)
        .where(GenerationSession.workspace_id == workspace_id)
        .order_by(GenerationSession.updated_at.desc())
        .limit(50)
    )
    return list(db.scalars(stmt))


@router.patch("/generation/sessions/{session_id}", response_model=GenerationSessionOut)
def update_generation_session(
    session_id: str, body: GenerationSessionUpdate, db: DbSession, user: CurrentUser
) -> GenerationSession:
    session = _require_generation_session(db, user, session_id)
    if body.title is not None:
        session.title = body.title
    db.commit()
    db.refresh(session)
    return session


@router.delete("/generation/sessions/{session_id}", status_code=204)
def delete_generation_session(session_id: str, db: DbSession, user: CurrentUser) -> Response:
    session = _require_generation_session(db, user, session_id)
    generations = list(db.scalars(select(GenerationJob).where(GenerationJob.session_id == session.id)))
    job_ids = [generation.job_id for generation in generations]
    db.execute(delete(GenerationJob).where(GenerationJob.session_id == session.id))
    if job_ids:
        db.execute(delete(Job).where(Job.id.in_(job_ids)))
    db.execute(delete(GenerationSession).where(GenerationSession.id == session.id))
    db.commit()
    return Response(status_code=204)


@router.get("/generation/models", response_model=list[GenerationModelOut])
def list_generation_models(db: DbSession, kind: str | None = None) -> list[GenerationModel]:
    ensure_builtin_generation_models(db)
    stmt = select(GenerationModel).where(GenerationModel.enabled.is_(True))
    if kind:
        stmt = stmt.where(GenerationModel.kind == kind)
    stmt = stmt.order_by(GenerationModel.provider, GenerationModel.model)
    return list(db.scalars(stmt))


@router.post("/generation/jobs", response_model=GenerationCreateResponse)
def create_generation(body: GenerationCreate, db: DbSession, user: CurrentUser) -> GenerationCreateResponse:
    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    ensure_builtin_generation_models(db)
    try:
        generation, job = create_generation_job(db, **body.model_dump())
    except GenerationDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    start_generation_thread(generation.id)
    return GenerationCreateResponse(
        generation=GenerationJobOut.model_validate(generation),
        job=job,
    )


@router.get("/generation/jobs", response_model=list[GenerationJobOut])
def list_generation_jobs(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    kind: str | None = None,
    session_id: str | None = None,
) -> list[GenerationJob]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(GenerationJob).where(GenerationJob.workspace_id == workspace_id)
    if session_id:
        session = _require_generation_session(db, user, session_id)
        if session.workspace_id != workspace_id:
            raise HTTPException(status_code=404, detail="Not found")
        stmt = stmt.where(GenerationJob.session_id == session_id)
    if kind:
        stmt = stmt.where(GenerationJob.kind == kind)
    stmt = stmt.order_by(GenerationJob.id.desc())
    return list(db.scalars(stmt))


def _require_generation_session(db: DbSession, user: CurrentUser, session_id: str) -> GenerationSession:
    session = db.get(GenerationSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Not found")
    ensure_workspace_access(db, user, session.workspace_id)
    return session


def _attach_legacy_generations(db: DbSession, workspace_id: str) -> None:
    legacy = list(
        db.scalars(
            select(GenerationJob)
            .where(GenerationJob.workspace_id == workspace_id, GenerationJob.session_id.is_(None))
            .order_by(GenerationJob.id)
        )
    )
    if not legacy:
        return
    session = GenerationSession(workspace_id=workspace_id, title="历史生成")
    db.add(session)
    db.flush()
    for generation in legacy:
        generation.session_id = session.id
    session.updated_at = now()
    db.commit()
