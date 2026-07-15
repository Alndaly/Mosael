from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GenerationJob, GenerationModel
from app.domain.jobs import create_job


class GenerationDomainError(ValueError):
    pass


def create_generation_job(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    provider: str,
    model: str,
    kind: str,
    prompt: str,
    parameters: dict[str, Any],
    source_asset_ids: list[str],
) -> tuple[GenerationJob, Any]:
    generation_model = db.scalar(
        select(GenerationModel).where(
            GenerationModel.provider == provider,
            GenerationModel.model == model,
            GenerationModel.kind == kind,
            GenerationModel.enabled.is_(True),
        )
    )
    if generation_model is None:
        raise GenerationDomainError("Generation model is not enabled or does not exist")

    request = {
        "project_id": project_id,
        "prompt": prompt,
        "parameters": parameters,
        "source_asset_ids": source_asset_ids,
    }
    job = create_job(
        db,
        workspace_id=workspace_id,
        kind="ai_generation",
        payload={
            "provider": provider,
            "model": model,
            "kind": kind,
            "request": request,
        },
        message="Queued for generation provider",
    )
    generation = GenerationJob(
        workspace_id=workspace_id,
        job_id=job.id,
        provider=provider,
        model=model,
        kind=kind,
        request=request,
    )
    db.add(generation)
    db.commit()
    db.refresh(generation)
    db.refresh(job)
    return generation, job
