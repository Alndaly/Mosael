from __future__ import annotations

import secrets

from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession
from app.db.models import ScheduledTask, now
from app.domain.scheduler import run_scheduled_task
from app.domain.scheduler.operations import SchedulerDomainError

"""Webhook 触发入口:外部系统(CI、IFTTT、n8n、curl)用任务级密钥
直接触发一个定时任务。不走登录态 —— 密钥即凭证,只对
trigger_type=webhook 的任务生效。"""

router = APIRouter(tags=["hooks"])


@router.post("/hooks/scheduled-tasks/{task_id}")
def fire_scheduled_task(task_id: str, secret: str, db: DbSession) -> dict:
    task = db.get(ScheduledTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    expected = str((task.payload or {}).get("webhook_secret") or "")
    if task.trigger_type != "webhook" or not expected or not secrets.compare_digest(expected, secret):
        raise HTTPException(status_code=403, detail="Invalid webhook secret")

    from app.workers.scheduler import _has_active_run, dispatch_job_for_task

    if _has_active_run(db, task.id):
        raise HTTPException(status_code=409, detail="Task already running")
    try:
        run, job = run_scheduled_task(db, task)
    except SchedulerDomainError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    dispatch_job_for_task(db, task, run, job)
    task.last_run_at = now()
    db.commit()
    return {"run_id": run.id, "job_id": job.id, "status": job.status}
