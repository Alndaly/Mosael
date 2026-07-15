from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.schemas import JobOut
from app.db.models import Job

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(workspace_id: str, db: DbSession, kind: str | None = None) -> list[Job]:
    stmt = select(Job).where(Job.workspace_id == workspace_id)
    if kind:
        stmt = stmt.where(Job.kind == kind)
    stmt = stmt.order_by(Job.created_at.desc())
    return list(db.scalars(stmt))


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: DbSession) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
