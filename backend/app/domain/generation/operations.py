from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GenerationJob, GenerationModel, GenerationSession, now
from app.domain.jobs import create_job


class GenerationDomainError(ValueError):
    pass


def create_generation_job(
    db: Session,
    *,
    workspace_id: str,
    session_id: str | None,
    project_id: str | None,
    provider: str,
    model: str,
    kind: str,
    prompt: str,
    negative_prompt: str,
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

    session = _resolve_session(db, workspace_id=workspace_id, session_id=session_id, prompt=prompt)
    request = {
        "project_id": project_id,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
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
        session_id=session.id,
        job_id=job.id,
        provider=provider,
        model=model,
        kind=kind,
        request=request,
    )
    session.updated_at = now()
    db.add(generation)
    db.commit()
    db.refresh(generation)
    db.refresh(job)
    return generation, job


def _resolve_session(db: Session, *, workspace_id: str, session_id: str | None, prompt: str) -> GenerationSession:
    if session_id:
        session = db.get(GenerationSession, session_id)
        if session is None or session.workspace_id != workspace_id:
            raise GenerationDomainError("Generation session not found in this workspace")
        if session.title == "新生成":
            session.title = _title_from_prompt(prompt)
        return session
    session = GenerationSession(workspace_id=workspace_id, title=_title_from_prompt(prompt))
    db.add(session)
    db.flush()
    return session


def _title_from_prompt(prompt: str) -> str:
    title = " ".join(prompt.strip().split())
    return title[:40] or "新生成"
