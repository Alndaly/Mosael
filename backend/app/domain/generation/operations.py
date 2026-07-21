from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers import get_provider
from app.db.models import GenerationJob, GenerationModel, GenerationSession, ProviderProfile, now
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
    provider_profile_id: str | None = None,
) -> tuple[GenerationJob, Any]:
    provider = provider.strip()
    model = model.strip()
    provider_profile = _resolve_provider_profile(db, provider_profile_id)
    if provider_profile is not None:
        provider = provider_profile.vendor
    else:
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
    if get_provider(provider, kind) is None:
        raise GenerationDomainError(f"Generation adapter is not available for {provider}/{kind}")

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
            "provider_profile_id": provider_profile.id if provider_profile else None,
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
        provider_profile_id=provider_profile.id if provider_profile else None,
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


def _resolve_provider_profile(db: Session, provider_profile_id: str | None) -> ProviderProfile | None:
    if not provider_profile_id:
        return None
    profile = db.get(ProviderProfile, provider_profile_id)
    if profile is None or not profile.enabled:
        raise GenerationDomainError("Generation provider profile is not available")
    return profile


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
