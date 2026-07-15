from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import GenerationCreate, GenerationCreateResponse, GenerationJobOut, GenerationModelOut
from app.core.permissions import ensure_workspace_access
from app.db.models import GenerationJob, GenerationModel
from app.domain.generation import create_generation_job, ensure_builtin_generation_models
from app.domain.generation.operations import GenerationDomainError

router = APIRouter(tags=["generation"])


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
    ensure_workspace_access(db, user, body.workspace_id)
    ensure_builtin_generation_models(db)
    try:
        generation, job = create_generation_job(db, **body.model_dump())
    except GenerationDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return GenerationCreateResponse(
        generation=GenerationJobOut.model_validate(generation),
        job=job,
    )


@router.get("/generation/jobs", response_model=list[GenerationJobOut])
def list_generation_jobs(workspace_id: str, db: DbSession, user: CurrentUser, kind: str | None = None) -> list[GenerationJob]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(GenerationJob).where(GenerationJob.workspace_id == workspace_id)
    if kind:
        stmt = stmt.where(GenerationJob.kind == kind)
    stmt = stmt.order_by(GenerationJob.id.desc())
    return list(db.scalars(stmt))
