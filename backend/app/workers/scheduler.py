from __future__ import annotations

import logging
import threading
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.domain.jobs import prune_task_events
from app.db.models import Job, ScheduledTask, ScheduledTaskRun, now
from app.domain.scheduler.operations import run_scheduled_task

"""
Scheduler runner (plan §13.4): a background loop that claims due tasks,
creates runs + jobs, dispatches known job kinds, and syncs run states.
The loop only triggers and records — heavy work happens in job workers.
"""

logger = logging.getLogger(__name__)

TICK_SECONDS = 5.0
TERMINAL_STATUSES = ("succeeded", "failed")
ACTIVE_STATUSES = ("queued", "running")

_stop_event: threading.Event | None = None


def start_scheduler_loop() -> None:
    global _stop_event
    if _stop_event is not None:
        return
    _stop_event = threading.Event()
    threading.Thread(target=_loop, args=(_stop_event,), daemon=True).start()


def stop_scheduler_loop() -> None:
    global _stop_event
    if _stop_event is not None:
        _stop_event.set()
        _stop_event = None


PRUNE_INTERVAL_SECONDS = 6 * 3600


def _loop(stop: threading.Event) -> None:
    last_prune = 0.0
    while not stop.wait(TICK_SECONDS):
        try:
            with SessionLocal() as db:
                tick(db)
                # Task-event retention (plan §12.3) piggybacks on this loop.
                if time.monotonic() - last_prune >= PRUNE_INTERVAL_SECONDS:
                    last_prune = time.monotonic()
                    removed = prune_task_events(db)
                    if removed:
                        logger.info("Task-event retention removed %d rows", removed)
        except Exception:  # the loop must survive any single bad tick
            logger.exception("Scheduler tick failed")


def tick(db: Session) -> list[str]:
    """One pass: sync run states, then claim + dispatch due tasks. Returns run ids created."""
    _sync_run_states(db)

    created: list[str] = []
    due = db.scalars(
        select(ScheduledTask).where(
            ScheduledTask.enabled.is_(True),
            ScheduledTask.next_run_at.is_not(None),
            ScheduledTask.next_run_at <= now(),
        )
    ).all()
    for task in due:
        if _has_active_run(db, task.id):
            # No reentry (plan §13.4): push the schedule forward and skip.
            from app.domain.scheduler.operations import compute_next_run_at

            task.next_run_at = compute_next_run_at(task.trigger_type, task.schedule)
            db.commit()
            continue
        run, job = run_scheduled_task(db, task)
        dispatch_job_for_task(db, task, run, job)
        if task.trigger_type == "once":
            task.enabled = False
            task.next_run_at = None
        task.last_run_at = now()
        db.commit()
        created.append(run.id)
    return created


def dispatch_job_for_task(db: Session, task: ScheduledTask, run: ScheduledTaskRun, job: Job) -> None:
    """Route known task kinds to their executors; unknown kinds stay queued."""
    payload: dict[str, Any] = task.payload or {}
    try:
        if task.kind == "workflow":
            from app.db.models import Workflow
            from app.domain.workflows.engine import start_workflow_job

            workflow = db.get(Workflow, str(payload.get("workflow_id", "")))
            if workflow is None:
                raise RuntimeError("任务绑定的工作流不存在")
            # 复用 run 的 job 作为工作流 job:引擎直接在它上面推进度/终态。
            job.payload = {**job.payload, "workflow_id": workflow.id}
            run.status = "running"
            db.commit()
            start_workflow_job(db, workflow, params=dict(payload.get("params") or {}), job=job)
        elif task.kind == "ai_generation":
            from app.domain.generation import create_generation_job
            from app.domain.generation.runner import start_generation_thread
            from app.domain.provider_defaults import resolve_default

            kind = str(payload.get("kind", "image")).strip() or "image"
            provider = str(payload.get("provider", "")).strip()
            model = str(payload.get("model", "")).strip()
            if not provider or not model:
                default_profile, default_model = resolve_default(db, kind)
                if default_profile is not None and default_model:
                    provider, model = default_profile.vendor, default_model
            if not provider or not model:
                raise RuntimeError("AI 生成任务缺少真实供应商或模型")
            generation, _generation_job = create_generation_job(
                db,
                workspace_id=task.workspace_id,
                session_id=None,
                project_id=task.project_id,
                provider=provider,
                model=model,
                kind=kind,
                prompt=str(payload.get("prompt", "")),
                negative_prompt=str(payload.get("negative_prompt", "")),
                parameters=dict(payload.get("parameters") or {}),
                source_asset_ids=[str(item) for item in payload.get("source_asset_ids") or []],
            )
            job.status = "running"
            job.message = f"Dispatched generation {generation.id}"
            run.status = "running"
            job.result = {"generation_id": generation.id, "generation_job_id": generation.job_id}
            db.commit()
            start_generation_thread(generation.id)
        elif task.kind == "render":
            from app.domain.render import start_export

            sequence_id = str(payload.get("sequence_id", ""))
            export_job = start_export(db, sequence_id)
            job.status = "running"
            job.message = f"Dispatched export {export_job.id}"
            run.status = "running"
            job.result = {"export_job_id": export_job.id}
            db.commit()
        else:
            job.message = f"No executor for task kind {task.kind}"
            db.commit()
    except Exception as exc:
        job.status = "failed"
        job.error = str(exc)[:500]
        run.status = "failed"
        run.error = str(exc)[:500]
        run.finished_at = now()
        db.commit()


def _has_active_run(db: Session, task_id: str) -> bool:
    active = db.scalar(
        select(ScheduledTaskRun.id)
        .join(Job, Job.id == ScheduledTaskRun.job_id, isouter=True)
        .where(
            ScheduledTaskRun.scheduled_task_id == task_id,
            ScheduledTaskRun.status.in_(ACTIVE_STATUSES),
        )
        .limit(1)
    )
    return active is not None


def _sync_run_states(db: Session) -> None:
    """Copy terminal states from dispatched child jobs onto their runs."""
    runs = db.scalars(
        select(ScheduledTaskRun).where(ScheduledTaskRun.status.in_(ACTIVE_STATUSES))
    ).all()
    for run in runs:
        if run.job_id is None:
            continue
        job = db.get(Job, run.job_id)
        if job is None:
            continue
        child_job_id = (job.result or {}).get("generation_job_id") or (job.result or {}).get("export_job_id")
        source = db.get(Job, child_job_id) if child_job_id else job
        if source is not None and source.status in TERMINAL_STATUSES:
            run.status = source.status
            run.error = source.error
            run.finished_at = now()
            job.status = source.status
            job.message = source.message
    db.commit()
