from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import Job, TaskEvent
from app.db.models import now as models_now

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = ("succeeded", "failed")

# Children (ffmpeg, ASR/TTS workers) belonging to a running job, so cancelling can actually
# stop the work. Without this, cancel only flipped a database row: ffmpeg ran to completion,
# burning CPU the user had asked to stop, and then the worker overwrote the cancellation with
# "succeeded" — the cancelled export reappeared in the library as if nothing had happened.
_CHILDREN: dict[str, Any] = {}
_CHILDREN_LOCK = threading.Lock()


def register_job_child(job_id: str, child: Any) -> None:
    """Associate a killable child (anything with .kill()) with a job for its lifetime."""
    with _CHILDREN_LOCK:
        _CHILDREN[job_id] = child


def unregister_job_child(job_id: str) -> None:
    with _CHILDREN_LOCK:
        _CHILDREN.pop(job_id, None)


def kill_job_child(job_id: str) -> bool:
    """Stop the child of a running job, if one is registered. True if something was killed."""
    with _CHILDREN_LOCK:
        child = _CHILDREN.get(job_id)
    if child is None:
        return False
    child.kill()
    return True


# Admission control for work that is heavy in CPU, GPU or memory. There was none: ten
# simultaneous exports meant ten x264 encoders plus up to eighty concurrent ffprobes, and ten
# transcribes meant ten torch interpreters — near-certain OOM on a laptop. Acquire a slot
# BEFORE opening a database session, never while holding one; see _run_proxy for what the other
# order costs. A sleeping thread is cheap, a pinned connection is not.
RENDER_SLOTS = threading.Semaphore(2)
ASR_SLOTS = threading.Semaphore(1)      # torch/funasr: one model in memory at a time
TTS_SLOTS = threading.Semaphore(1)
GENERATION_SLOTS = threading.Semaphore(4)  # mostly waiting on a remote API


def run_job_guarded(job_id: str, body: Callable[[], None], *, what: str = "job") -> None:
    """Run a worker body so that no failure can leave the job silently queued.

    Every worker began with `db.get(Job, job_id)` OUTSIDE its try. That is the call that checks
    a connection out of the pool, so when the pool was exhausted it raised, the daemon thread
    died, and the row stayed `queued` with no error — forever, since reconcile only runs at
    startup. A backfill of 60 videos produced 45 such jobs.

    Anything the body does not handle is recorded on the job here instead.
    """
    try:
        body()
    except Exception as exc:  # noqa: BLE001 — a worker thread must never die silently
        logger.exception("%s worker failed", what)
        try:
            with SessionLocal() as db:
                job = db.get(Job, job_id)
                if job is not None and job.status not in TERMINAL_STATUSES:
                    job.status = "failed"
                    job.error = str(exc)[:500]
                    job.message = f"{what} 失败"
                    db.add(TaskEvent(job_id=job.id, type="job.failed", payload={"stage": "worker"}))
                    db.commit()
        except Exception:  # noqa: BLE001 — the DB is what failed; nothing left to try
            logger.exception("could not record the failure of %s %s", what, job_id)


def finish_job(db: Session, job: Job, **fields: Any) -> bool:
    """Write a terminal state unless the job already reached one.

    Workers held a Job loaded at the start of the run and assigned to it at the end, so a
    cancellation landing in between was silently clobbered. Re-read first and skip the write if
    the job is already settled; the caller uses the return value to skip the rest of its
    success path too (registering an export as an asset, emitting job.succeeded).
    """
    db.refresh(job)
    if job.status in TERMINAL_STATUSES:
        return False
    for key, value in fields.items():
        setattr(job, key, value)
    return True
# Retention (plan §12.3): active jobs keep every event; terminal jobs keep the
# most recent few; terminal jobs older than the window lose all detail events.
TERMINAL_KEEP_EVENTS = 5
EVENT_RETENTION_DAYS = 30


# Publish jobs are driven by the external desktop worker (a separate Electron
# process that polls the publish-worker endpoint), so they can legitimately stay
# "running" across a backend restart. Every other kind runs in an in-process
# daemon thread that dies with the process — those are orphaned by a restart.
EXTERNAL_WORKER_KINDS = ("publish",)


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


def reconcile_orphaned_jobs(db: Session) -> int:
    """Fail in-process jobs left `queued`/`running` by a backend restart.

    Their daemon-thread workers cannot survive the process, so they would
    otherwise sit frozen at their last progress forever. Publish jobs are exempt
    (external worker). Returns the number of jobs reconciled.
    """
    stale = db.scalars(
        select(Job)
        .where(Job.status.in_(("queued", "running")))
        .where(Job.kind.notin_(EXTERNAL_WORKER_KINDS))
    ).all()
    for job in stale:
        job.status = "failed"
        job.message = "已中断"
        job.error = "后端重启导致任务中断,请重新发起"
        db.add(TaskEvent(job_id=job.id, type="job.failed", payload={"reason": "backend_restart"}))
    if stale:
        db.commit()
    return len(stale)


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
    # Stop the actual work, not just the row describing it.
    killed = kill_job_child(job.id)
    if killed:
        db.add(TaskEvent(job_id=job.id, type="job.child_killed", payload={}))

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
    reference = now or models_now()  # utcnow() is deprecated; models_now is the same naive UTC
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
