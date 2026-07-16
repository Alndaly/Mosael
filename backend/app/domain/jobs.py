from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import Job, TaskEvent

TERMINAL_STATUSES = ("succeeded", "failed")
# Retention (plan §12.3): active jobs keep every event; terminal jobs keep the
# most recent few; terminal jobs older than the window lose all detail events.
TERMINAL_KEEP_EVENTS = 5
EVENT_RETENTION_DAYS = 30


def create_job(
    db: Session,
    *,
    workspace_id: str,
    kind: str,
    payload: dict[str, Any],
    message: str = "Queued",
) -> Job:
    job = Job(workspace_id=workspace_id, kind=kind, payload=payload, message=message)
    db.add(job)
    db.flush()
    db.add(TaskEvent(job_id=job.id, type="job.queued", payload={"message": message}))
    return job


def prune_task_events(db: Session, *, now: datetime | None = None) -> int:
    """Apply the retention rules to task_events. Returns rows deleted."""
    reference = now or datetime.utcnow()
    cutoff = reference - timedelta(days=EVENT_RETENTION_DAYS)
    removed = 0

    terminal_jobs = db.scalars(select(Job).where(Job.status.in_(TERMINAL_STATUSES))).all()
    for job in terminal_jobs:
        if job.updated_at < cutoff:
            result = db.execute(delete(TaskEvent).where(TaskEvent.job_id == job.id))
            removed += result.rowcount or 0
            continue
        keep_ids = list(
            db.scalars(
                select(TaskEvent.id)
                .where(TaskEvent.job_id == job.id)
                .order_by(TaskEvent.created_at.desc())
                .limit(TERMINAL_KEEP_EVENTS)
            )
        )
        result = db.execute(
            delete(TaskEvent).where(TaskEvent.job_id == job.id, TaskEvent.id.not_in(keep_ids))
        )
        removed += result.rowcount or 0
    db.commit()
    return removed


def clear_finished_jobs(db: Session, workspace_id: str) -> int:
    """Remove terminal jobs (their events cascade). Returns jobs deleted."""
    jobs = db.scalars(
        select(Job).where(Job.workspace_id == workspace_id, Job.status.in_(TERMINAL_STATUSES))
    ).all()
    for job in jobs:
        db.execute(delete(TaskEvent).where(TaskEvent.job_id == job.id))
        db.delete(job)
    db.commit()
    return len(jobs)
