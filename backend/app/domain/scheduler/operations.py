from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.db.models import ScheduledTask, ScheduledTaskRun, now
from app.domain.jobs import create_job

logger = logging.getLogger(__name__)


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
    if trigger_type == "webhook" and not payload.get("webhook_secret"):
        # 外部触发路由不走登录态,按任务级密钥鉴权。
        payload = {**payload, "webhook_secret": secrets.token_urlsafe(24)}
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
        next_run_at=compute_next_run_at(trigger_type, schedule, timezone=timezone) if enabled else None,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def update_scheduled_task(db: Session, task: ScheduledTask, changes: dict[str, Any]) -> ScheduledTask:
    for key, value in changes.items():
        if value is not None:
            setattr(task, key, value)
    task.next_run_at = compute_next_run_at(task.trigger_type, task.schedule, timezone=task.timezone) if task.enabled else None
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
        # 定时执行没有"当时的操作人",但一定有一个"当初挂上去的人" —— 用它的钥匙、算它的额度。
        created_by=task.owner_user_id,
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
    task.next_run_at = compute_next_run_at(task.trigger_type, task.schedule, timezone=task.timezone)
    db.commit()
    db.refresh(task)
    db.refresh(run)
    db.refresh(job)
    return run, job


def compute_next_run_at(
    trigger_type: str,
    schedule: dict[str, Any],
    reference: datetime | None = None,
    timezone: str = "UTC",
) -> datetime | None:
    """下一次触发时刻(**返回 UTC**)。支持 manual/once/interval/daily/weekly。

    `daily` / `weekly` 里的钟点说的是**任务所在时区**的钟点 —— 「每天 09:00」在 +08 的人那里
    就该是他那儿的早上九点。此前这一列存了却从没被读过:排程一律按 UTC 算,于是同一个人设的
    "09:00" 实际 17:00 才跑。一个存得下、看得见、却不起作用的设置比没有更坏。

    时区名不认识就退回 UTC:一个任务写错配置,不该让整个调度器停摆。
    """
    current = reference or now()
    zone = _zone(timezone)
    if trigger_type in ("manual", "webhook"):
        # 都不进调度器轮询:手动靠 UI,webhook 靠外部 HTTP 触发。
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
        local = current.replace(tzinfo=UTC).astimezone(zone)
        candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if candidate <= local:
            candidate += timedelta(days=1)
        return candidate.astimezone(UTC).replace(tzinfo=None)
    if trigger_type == "weekly":
        weekday = schedule.get("weekday")
        if not isinstance(weekday, int) or not 0 <= weekday <= 6:
            raise SchedulerDomainError("weekly schedule requires weekday 0-6 (Monday=0)")
        hour, minute = _parse_time(schedule)
        local = current.replace(tzinfo=UTC).astimezone(zone)
        candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (weekday - candidate.weekday()) % 7
        candidate += timedelta(days=days_ahead)
        if candidate <= local:
            candidate += timedelta(days=7)
        return candidate.astimezone(UTC).replace(tzinfo=None)
    raise SchedulerDomainError(f"Unsupported trigger type: {trigger_type}")


def _zone(name: str) -> ZoneInfo:
    """时区名 → tzinfo。不认识就 UTC(见 compute_next_run_at 的说明)。"""
    try:
        return ZoneInfo(name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("定时任务的时区 %r 不认识,按 UTC 算", name)
        return ZoneInfo("UTC")


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
