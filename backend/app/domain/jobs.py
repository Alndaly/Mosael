from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Job, TaskEvent


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
