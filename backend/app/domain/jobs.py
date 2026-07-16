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


def cancel_job(db: Session, job: Job) -> Job:
    """用户主动取消:job 落终态,发布任务同步撤单,工作流/批量在节点边界停下。

    线程内正在执行的节点无法安全掐断;engine/batch 每个节点边界都会重读 job
    状态,看到已取消就不再继续——"停止中断"语义是节点粒度的。
    """
    if job.status not in ("queued", "running"):
        raise ValueError("任务已结束,无法取消")
    job.status = "failed"
    job.error = "已取消"
    job.message = "已取消"
    db.add(TaskEvent(job_id=job.id, type="job.cancelled", payload={}))

    if job.kind == "publish":
        from app.db.models import PublishTask

        task = db.scalar(select(PublishTask).where(PublishTask.job_id == job.id))
        if task is not None and task.status not in ("success", "prepared", "failed", "cancelled"):
            task.status = "cancelled"
    db.commit()
    db.refresh(job)
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
