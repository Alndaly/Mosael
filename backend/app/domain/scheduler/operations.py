from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import ScheduledTask, ScheduledTaskRun, Workflow, now
from app.domain.jobs import create_job

logger = logging.getLogger(__name__)


class SchedulerDomainError(LocalizedError, ValueError):
    """定时任务说不行。带文案 key(`schedErr_*`)。"""


class SchedulerBusy(SchedulerDomainError):
    """上一次还没跑完。定时任务不重入(plan §13.4)。"""


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
    from app.domain.scheduler.executors import SCHEDULED_EXECUTORS

    if kind not in SCHEDULED_EXECUTORS:
        # 此前什么都收:认不出的种类建得出来,到点排一个任务,然后永远停在"排队中"。
        raise SchedulerDomainError("schedErr_badKind", kinds=" / ".join(SCHEDULED_EXECUTORS))
    if enabled:
        ensure_runnable(db, kind=kind, workspace_id=workspace_id, payload=payload)
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
    # 按**改完之后**的样子判:同一次既改绑到一张在的图、又打开开关,是可以的。停用永远放行 ——
    # 一个跑不起来的任务至少要关得掉。
    enabled = task.enabled if changes.get("enabled") is None else changes["enabled"]
    if changes.get("payload") is not None:
        # 触发密钥**归服务端管**:只由建任务和 rotate_webhook_secret 写。客户端带着一份旧 payload
        # 回来保存(编辑名称/参数时就是这样)不能把刚重置过的密钥写回去,也不能自己指定一个。
        changes = {**changes, "payload": _keep_secret(task.payload, changes["payload"])}
    payload = task.payload if changes.get("payload") is None else changes["payload"]
    if enabled:
        ensure_runnable(db, kind=task.kind, workspace_id=task.workspace_id, payload=payload)
    for key, value in changes.items():
        if value is not None:
            setattr(task, key, value)
    task.next_run_at = compute_next_run_at(task.trigger_type, task.schedule, timezone=task.timezone) if task.enabled else None
    db.commit()
    db.refresh(task)
    return task


def _keep_secret(current: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    incoming = {k: v for k, v in incoming.items() if k != "webhook_secret"}
    secret = (current or {}).get("webhook_secret")
    return {**incoming, "webhook_secret": secret} if secret else incoming


def rotate_webhook_secret(db: Session, task: ScheduledTask) -> ScheduledTask:
    """换一把触发密钥,旧的立刻失效 —— 触发地址泄漏时的补救。

    密钥同时管着触发、查进度和取消三件事(见 api/routes/hooks),换掉它三扇门一起关上。
    已经在跑的那次不受影响:它不再需要密钥。
    """
    if task.trigger_type != "webhook":
        raise SchedulerDomainError("schedErr_notWebhook")
    task.payload = {**(task.payload or {}), "webhook_secret": secrets.token_urlsafe(24)}
    db.commit()
    db.refresh(task)
    return task


def trigger_scheduled_task(db: Session, task: ScheduledTask) -> tuple[ScheduledTaskRun, Any]:
    """跑一次定时任务。**三个触发入口共用**:调度循环到点、「立即运行」、webhook。

    此前三处各拼一套:调度循环查了重入、webhook 查了(借 worker 模块的私有函数)、「立即运行」
    没查 —— 连点两下就是两次并发的同一个任务。
    """
    from app.domain.scheduler.executors import dispatch_scheduled_job, has_active_run

    # 事前就知道跑不起来的,不开运行记录 —— 此前绑的工作流被删了照样能点「立即运行」,
    # 每点一次多一条 0.0 秒的失败。
    ensure_runnable(db, kind=task.kind, workspace_id=task.workspace_id, payload=task.payload)
    if has_active_run(db, task.id):
        raise SchedulerBusy("schedErr_busy")
    run, job = _open_run(db, task)
    dispatch_scheduled_job(db, task, run, job)
    if task.trigger_type == "once":
        task.enabled = False
        task.next_run_at = None
    task.last_run_at = now()
    db.commit()
    db.refresh(run)
    db.refresh(job)
    return run, job


def ensure_runnable(db: Session, *, kind: str, workspace_id: str, payload: dict[str, Any] | None) -> None:
    """这种任务、带着这份 payload,现在跑得起来吗?跑不起来就说为什么(见 SCHEDULED_READINESS)。

    **不变式:启用着的任务一定跑得起来。** 建任务、打开开关、三个触发入口都经这里;
    而让它跑不起来的那件事(删工作流)在发生的那一刻就把任务停掉(stop_tasks_bound_to_workflow)。
    """
    from app.domain.scheduler.executors import SCHEDULED_READINESS

    check = SCHEDULED_READINESS.get(kind)
    problem = check(db, workspace_id, payload or {}) if check else None
    if problem:
        raise SchedulerDomainError(problem)


def stop_tasks_bound_to_workflow(db: Session, workflow: Workflow) -> list[ScheduledTask]:
    """一张工作流要被删了:绑着它的定时任务**当场停用**。不提交,由删除的那一方一起提交。

    此前删工作流什么都不管,任务仍是「启用」、仍按排程触发,每一次都落一条「工作流不存在」的
    失败;手动任务则照样能点「立即运行」。任务本身留着(连同它的运行记录和那条「绑定的工作流
    已删除」),删不删由人决定 —— 但它不能再自己跑。
    """
    tasks = db.scalars(
        select(ScheduledTask).where(
            ScheduledTask.workspace_id == workflow.workspace_id,
            ScheduledTask.kind == "workflow",
            ScheduledTask.enabled.is_(True),
        )
    ).all()
    stopped = [task for task in tasks if str((task.payload or {}).get("workflow_id", "")) == workflow.id]
    for task in stopped:
        task.enabled = False
        task.next_run_at = None
    return stopped


def _open_run(db: Session, task: ScheduledTask) -> tuple[ScheduledTaskRun, Any]:
    if not task.enabled:
        raise SchedulerDomainError("schedErr_disabled")

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
            "subject": task.name,
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
            raise SchedulerDomainError("schedErr_onceNeedsRunAt")
        return _parse_datetime(value)
    if trigger_type == "interval":
        value = schedule.get("seconds")
        if not isinstance(value, int | float) or value <= 0:
            raise SchedulerDomainError("schedErr_intervalNeedsSeconds")
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
            raise SchedulerDomainError("schedErr_weeklyNeedsWeekday")
        hour, minute = _parse_time(schedule)
        local = current.replace(tzinfo=UTC).astimezone(zone)
        candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (weekday - candidate.weekday()) % 7
        candidate += timedelta(days=days_ahead)
        if candidate <= local:
            candidate += timedelta(days=7)
        return candidate.astimezone(UTC).replace(tzinfo=None)
    raise SchedulerDomainError("schedErr_unsupportedTrigger", trigger=trigger_type)


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
        raise SchedulerDomainError("schedErr_badTime") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise SchedulerDomainError("schedErr_badTime")
    return hour, minute


def _parse_datetime(value: str) -> datetime:
    normalized = value.removesuffix("Z")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise SchedulerDomainError("schedErr_badRunAt") from exc
