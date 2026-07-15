from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import ScheduledTask, ScheduledTaskRun, now
from app.domain.jobs import create_job


class SchedulerDomainError(ValueError):
    pass


def create_scheduled_task(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None,
    name: str,
    kind: str,
    trigger_type: str,
    schedule: dict[str, Any],
    timezone: str,
    enabled: bool,
    payload: dict[str, Any],
) -> ScheduledTask:
    task = ScheduledTask(
        workspace_id=workspace_id,
        project_id=project_id,
        name=name,
        kind=kind,
        trigger_type=trigger_type,
        schedule=schedule,
        timezone=timezone,
        enabled=enabled,
        payload=payload,
        next_run_at=compute_next_run_at(trigger_type, schedule) if enabled else None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_scheduled_task(db: Session, task: ScheduledTask, changes: dict[str, Any]) -> ScheduledTask:
    for key, value in changes.items():
        if value is not None:
            setattr(task, key, value)
    task.next_run_at = compute_next_run_at(task.trigger_type, task.schedule) if task.enabled else None
    db.commit()
    db.refresh(task)
    return task


def run_scheduled_task(db: Session, task: ScheduledTask) -> tuple[ScheduledTaskRun, Any]:
    if not task.enabled:
        raise SchedulerDomainError("Scheduled task is disabled")

    run = ScheduledTaskRun(scheduled_task_id=task.id, status="queued", started_at=now())
    db.add(run)
    db.flush()
    job = create_job(
        db,
        workspace_id=task.workspace_id,
        kind=task.kind,
        payload={
            "scheduled_task_id": task.id,
            "scheduled_task_run_id": run.id,
            "project_id": task.project_id,
            "payload": task.payload,
        },
        message=f"Queued by scheduled task: {task.name}",
    )
    run.job_id = job.id
    task.next_run_at = compute_next_run_at(task.trigger_type, task.schedule)
    db.commit()
    db.refresh(task)
    db.refresh(run)
    db.refresh(job)
    return run, job


def compute_next_run_at(
    trigger_type: str, schedule: dict[str, Any], reference: datetime | None = None
) -> datetime | None:
    """Next trigger time (UTC). Supports manual/once/interval/daily/weekly."""
    current = reference or now()
    if trigger_type == "manual":
        return None
    if trigger_type == "once":
        value = schedule.get("run_at")
        if not isinstance(value, str):
            raise SchedulerDomainError("once schedule requires run_at")
        return _parse_datetime(value)
    if trigger_type == "interval":
        value = schedule.get("seconds")
        if not isinstance(value, int | float) or value <= 0:
            raise SchedulerDomainError("interval schedule requires positive seconds")
        return current + timedelta(seconds=float(value))
    if trigger_type == "daily":
        hour, minute = _parse_time(schedule)
        candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= current:
            candidate += timedelta(days=1)
        return candidate
    if trigger_type == "weekly":
        weekday = schedule.get("weekday")
        if not isinstance(weekday, int) or not 0 <= weekday <= 6:
            raise SchedulerDomainError("weekly schedule requires weekday 0-6 (Monday=0)")
        hour, minute = _parse_time(schedule)
        candidate = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (weekday - candidate.weekday()) % 7
        candidate += timedelta(days=days_ahead)
        if candidate <= current:
            candidate += timedelta(days=7)
        return candidate
    raise SchedulerDomainError(f"Unsupported trigger type: {trigger_type}")


def _parse_time(schedule: dict[str, Any]) -> tuple[int, int]:
    value = schedule.get("time", "09:00")
    try:
        hour_text, minute_text = str(value).split(":", 1)
        hour, minute = int(hour_text), int(minute_text)
    except ValueError as exc:
        raise SchedulerDomainError("time must be HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise SchedulerDomainError("time must be HH:MM")
    return hour, minute


def _parse_datetime(value: str) -> datetime:
    normalized = value.removesuffix("Z")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SchedulerDomainError("run_at must be an ISO datetime") from exc
