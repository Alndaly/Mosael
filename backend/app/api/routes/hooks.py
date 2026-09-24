"""Webhook 入口:外部系统(CI、IFTTT、n8n、curl)凭任务级密钥触发一个定时任务,并跟进它。

不走登录态 —— **密钥即凭证**,只对 trigger_type=webhook 的任务生效。同一把密钥管三件事:
触发、查这次运行到哪了、取消它。此前只有触发:外部系统点了就只能干等,既不知道跑完没有,
也停不下来(查进度和取消的接口都要登录,而外部系统手上只有这把密钥)。

查与取消只认**这个任务自己的**运行:run_id 是别的任务的,一律当作不存在 —— 否则一把泄漏的
密钥就能拿着猜来的 run_id 去看、去停别人的任务。密钥泄漏了在任务页重置
(POST /scheduled-tasks/{id}/webhook-secret),三扇门一起关上。
"""

from __future__ import annotations

import secrets
from datetime import datetime

from fastapi import APIRouter, HTTPException

from app.api.deps import DbSession
from app.api.schemas import JobOut
from app.core.i18n import tr
from app.db.models import Job, ScheduledTask, ScheduledTaskRun
from app.domain.jobs import JobError, cancel_job
from app.domain.scheduler import SchedulerDomainError, trigger_scheduled_task
from app.api.schemas.base import ApiModel

router = APIRouter(tags=["hooks"])


class HookRunOut(ApiModel):
    """外部系统看到的一次运行。进度与说明取自背后那个任务(按请求的 Accept-Language 说)。"""

    run_id: str
    job_id: str | None = None
    #: queued / running / succeeded / failed / cancelled
    status: str
    #: 0–1
    progress: float = 0
    message: str = ""
    error: str | None = None
    result: dict = {}
    started_at: datetime | None = None
    finished_at: datetime | None = None


def _task(db, task_id: str, secret: str) -> ScheduledTask:
    task = db.get(ScheduledTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail=tr("hookErr_taskNotFound"))
    expected = str((task.payload or {}).get("webhook_secret") or "")
    if task.trigger_type != "webhook" or not expected or not secrets.compare_digest(expected, secret):
        raise HTTPException(status_code=403, detail=tr("hookErr_badSecret"))
    return task


def _run(db, task: ScheduledTask, run_id: str) -> ScheduledTaskRun:
    run = db.get(ScheduledTaskRun, run_id)
    if run is None or run.scheduled_task_id != task.id:
        raise HTTPException(status_code=404, detail=tr("hookErr_runNotFound"))
    return run


def _out(db, run: ScheduledTaskRun) -> HookRunOut:
    job = db.get(Job, run.job_id) if run.job_id else None
    if job is None:
        return HookRunOut(run_id=run.id, status=run.status, error=run.error, result=run.result or {},
                          started_at=run.started_at, finished_at=run.finished_at)
    shown = JobOut.model_validate(job)  # 按请求语言渲染 message / error(见 JobOut)
    # 任务系统把「被取消」记成 failed + jobErr_cancelled。对外单列成 cancelled:调用方对
    # 「我自己停掉的」和「跑挂了」该做的事不一样(后者要报警、要重试)。
    status = "cancelled" if job.status == "failed" and job.error_key == "jobErr_cancelled" else job.status
    return HookRunOut(
        run_id=run.id, job_id=job.id, status=status, progress=job.progress or 0,
        message=shown.message, error=shown.error, result=job.result or {},
        started_at=run.started_at, finished_at=run.finished_at,
    )


@router.post("/hooks/scheduled-tasks/{task_id}")
def fire_scheduled_task(task_id: str, secret: str, db: DbSession) -> dict:
    task = _task(db, task_id, secret)
    try:
        run, job = trigger_scheduled_task(db, task)
    except SchedulerDomainError as exc:  # 停用了、上一次还没跑完、绑的工作流没了
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"run_id": run.id, "job_id": job.id, "status": job.status}


@router.get("/hooks/scheduled-tasks/{task_id}/runs/{run_id}", response_model=HookRunOut)
def get_hook_run(task_id: str, run_id: str, secret: str, db: DbSession) -> HookRunOut:
    """这次运行到哪了。外部系统拿触发时返回的 run_id 轮询,直到 status 落到终态。"""
    task = _task(db, task_id, secret)
    return _out(db, _run(db, task, run_id))


@router.post("/hooks/scheduled-tasks/{task_id}/runs/{run_id}/cancel", response_model=HookRunOut)
def cancel_hook_run(task_id: str, run_id: str, secret: str, db: DbSession) -> HookRunOut:
    """取消这次运行。节点粒度:正在执行的那一步跑完就停,派生的子任务一并取消(见 jobs.cancel_job)。"""
    task = _task(db, task_id, secret)
    run = _run(db, task, run_id)
    job = db.get(Job, run.job_id) if run.job_id else None
    if job is None:
        raise HTTPException(status_code=409, detail=tr("jobErr_alreadyFinished"))
    try:
        cancel_job(db, job)
    except JobError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.refresh(run)
    return _out(db, run)
