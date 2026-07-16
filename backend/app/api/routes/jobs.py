from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import JobOut, TaskEventOut
from app.core.permissions import ensure_workspace_access
from app.db.models import Job, TaskEvent
from app.domain.jobs import cancel_job, clear_finished_jobs

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(workspace_id: str, db: DbSession, user: CurrentUser, kind: str | None = None) -> list[Job]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(Job).where(Job.workspace_id == workspace_id)
    if kind:
        stmt = stmt.where(Job.kind == kind)
    stmt = stmt.order_by(Job.created_at.desc())
    return list(db.scalars(stmt))


@router.delete("/jobs/finished")
def delete_finished_jobs(workspace_id: str, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_access(db, user, workspace_id)
    return {"removed": clear_finished_jobs(db, workspace_id)}


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: DbSession, user: CurrentUser) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    ensure_workspace_access(db, user, job.workspace_id)
    return job


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job_route(job_id: str, db: DbSession, user: CurrentUser) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    ensure_workspace_access(db, user, job.workspace_id)
    try:
        return cancel_job(db, job)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/events", response_model=list[TaskEventOut])
def list_job_events(job_id: str, db: DbSession, user: CurrentUser) -> list[TaskEvent]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    ensure_workspace_access(db, user, job.workspace_id)
    events = list(
        db.scalars(
            select(TaskEvent)
            .where(TaskEvent.job_id == job_id)
            .order_by(TaskEvent.created_at.desc())
            .limit(30)
        )
    )
    return list(reversed(events))
