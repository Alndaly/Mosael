"""定时任务**到点之后做什么**。一种任务一个执行体,登记在 SCHEDULED_EXECUTORS。

此前这段是 workers/scheduler 里的一条 if 链,而"立即运行"接口和 webhook 各自从 worker 模块里
借它(连带一个私有函数)。它是领域规则,不是轮询循环的一部分:三个触发入口都经
operations.trigger_scheduled_task 到这里。

执行体收到的是一个包装任务(kind = 定时任务的种类)。它可以直接在这个任务上干活(工作流),
也可以把活交给另一个任务(生成、导出)—— 那时把那个任务的 id 记在 `result.delegated_job_id`,
`sync_run_states` 据此把它的终态抄回来。交出去的任务建在包装任务的上下文里,所以是它的子任务,
取消会级联(ADR-0018)。

加一种可定时的任务 = 写一个执行体、登记一行,再在任务目录(job_catalog)里有它。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import Job, ScheduledTask, ScheduledTaskRun, Workflow, now
from app.domain.jobs import TERMINAL_STATUSES, blame, finish_job, reset_parent_job, say, set_parent_job

logger = logging.getLogger(__name__)


class ScheduledRunError(LocalizedError, RuntimeError):
    """这一次定时运行派不出去。带文案 key(`schedErr_*`),经 `jobs.blame` 连 key 一起落进任务的失败原因。"""

ACTIVE_RUN_STATUSES = ("queued", "running")

Executor = Callable[[Session, ScheduledTask, ScheduledTaskRun, Job], None]


def bound_workflow(db: Session, *, workspace_id: str, payload: dict[str, Any] | None) -> Workflow | None:
    """工作流任务指着的那张图。不在了(删了,或者是别的工作区的)就是 None。"""
    workflow = db.get(Workflow, str((payload or {}).get("workflow_id", "")))
    if workflow is None or workflow.workspace_id != workspace_id:
        return None
    return workflow


def _run_workflow(db: Session, task: ScheduledTask, run: ScheduledTaskRun, job: Job) -> None:
    from app.domain.workflows.engine import start_workflow_job

    payload: dict[str, Any] = task.payload or {}
    workflow = bound_workflow(db, workspace_id=task.workspace_id, payload=payload)
    if workflow is None:
        # 启用、触发之前都拦过(见 SCHEDULED_READINESS);走到这里是派发的这一瞬间图被删了。
        raise ScheduledRunError("schedErr_workflowMissing")
    # 复用包装任务作为工作流任务:引擎直接在它上面推进度和终态。
    job.payload = {**job.payload, "workflow_id": workflow.id}
    run.status = "running"
    db.commit()
    start_workflow_job(db, workflow, created_by=task.owner_user_id, params=dict(payload.get("params") or {}), job=job)


def _run_generation(db: Session, task: ScheduledTask, run: ScheduledTaskRun, job: Job) -> None:
    from app.domain.generation import create_generation_job
    from app.domain.generation.operations import parse_source_assets
    from app.domain.generation.runner import start_generation_thread

    payload: dict[str, Any] = task.payload or {}
    kind = str(payload.get("kind", "image")).strip() or "image"
    # 没点名模型时漏斗用挂任务那个人的默认(generation.operations._default_model)。
    generation, delegated = create_generation_job(
        db,
        workspace_id=task.workspace_id,
        session_id=None,
        project_id=task.project_id,
        created_by=task.owner_user_id,
        provider=str(payload.get("provider", "")),
        provider_profile_id=str(payload.get("provider_profile_id", "")).strip() or None,
        model=str(payload.get("model", "")),
        kind=kind,
        prompt=str(payload.get("prompt", "")),
        negative_prompt=str(payload.get("negative_prompt", "")),
        parameters=dict(payload.get("parameters") or {}),
        source_assets=parse_source_assets(payload.get("source_assets"), kind=kind),
    )
    if _delegate(db, run, job, delegated.id, f"Dispatched generation {generation.id}"):
        start_generation_thread(generation.id)


def _run_export(db: Session, task: ScheduledTask, run: ScheduledTaskRun, job: Job) -> None:
    from app.domain.render import start_export

    payload: dict[str, Any] = task.payload or {}
    delegated = start_export(db, str(payload.get("sequence_id", "")), created_by=task.owner_user_id)
    _delegate(db, run, job, delegated.id, f"Dispatched export {delegated.id}")


def _delegate(db: Session, run: ScheduledTaskRun, job: Job, delegated_id: str, message: str) -> bool:
    """包装任务把活交给了另一个任务。包装任务已被取消时返回 False(交出去的那个随级联停下)。"""
    if not finish_job(db, job, status="running"):
        db.commit()
        return False
    say(job, message)
    run.status = "running"
    job.result = {"delegated_job_id": delegated_id}
    db.commit()
    return True


SCHEDULED_EXECUTORS: dict[str, Executor] = {
    "workflow": _run_workflow,
    "ai_generation": _run_generation,
    "render": _run_export,
}


#: 一种任务**现在跑得起来吗**:跑不起来时给出文案 key,跑得起来给 None。
#:
#: 它和执行体是两件事:执行体在派发的那一刻才发现问题,那时运行记录和任务都已经建好了,只能
#: 记一条失败。而「绑的工作流被删了」是一个**事前就知道**的状态 —— 此前它照样能启用、能点
#: 「立即运行」,每点一次就多一条 0.0 秒的失败记录。启用、建任务、三个触发入口都先问这里
#: (operations.ensure_runnable)。没登记的种类没有事前条件。
Readiness = Callable[[Session, str, dict[str, Any]], str | None]


def _workflow_ready(db: Session, workspace_id: str, payload: dict[str, Any]) -> str | None:
    return None if bound_workflow(db, workspace_id=workspace_id, payload=payload) else "schedErr_workflowGone"


SCHEDULED_READINESS: dict[str, Readiness] = {
    "workflow": _workflow_ready,
}


def dispatch_scheduled_job(db: Session, task: ScheduledTask, run: ScheduledTaskRun, job: Job) -> None:
    """按种类派给执行体。执行体里建的任务归这个包装任务(严格档:包装任务结束了就不再派生)。"""
    executor = SCHEDULED_EXECUTORS.get(task.kind)
    token = set_parent_job(job.id)
    try:
        if executor is None:
            # 建任务时已经拦过;走到这里说明种类是老数据里的。
            raise ScheduledRunError("schedErr_unsupportedKind", kind=task.kind)
        executor(db, task, run, job)
    except Exception as exc:  # noqa: BLE001 — 任何失败都要落进运行记录,否则它永远是"进行中"
        logger.warning("定时任务 %s 派发失败:%s", task.id, exc)
        if not finish_job(db, job, status="failed", **blame(exc)):
            db.commit()
            return
        run.status = "failed"
        run.error = str(exc)[:500]
        run.finished_at = now()
        db.commit()
    finally:
        reset_parent_job(token)


def has_active_run(db: Session, task_id: str) -> bool:
    return db.scalar(
        select(ScheduledTaskRun.id)
        .where(
            ScheduledTaskRun.scheduled_task_id == task_id,
            ScheduledTaskRun.status.in_(ACTIVE_RUN_STATUSES),
        )
        .limit(1)
    ) is not None


def sync_run_states(db: Session) -> None:
    """把任务的终态抄到运行记录上。活交出去了的,看交出去的那个任务。"""
    runs = db.scalars(select(ScheduledTaskRun).where(ScheduledTaskRun.status.in_(ACTIVE_RUN_STATUSES))).all()
    for run in runs:
        job = db.get(Job, run.job_id) if run.job_id else None
        if job is None:
            continue
        db.refresh(job)
        delegated_id = (job.result or {}).get("delegated_job_id")
        source = job if job.status in TERMINAL_STATUSES or not delegated_id else db.get(Job, delegated_id)
        if source is None or source.status not in TERMINAL_STATUSES:
            continue
        # 包装任务已经被取消的,交出去的那个迟到的结果不改写它。
        if source is not job and not finish_job(db, job, status=source.status, error=source.error):
            source = job
        run.status = source.status
        run.error = source.error
        run.finished_at = now()
        say(job, source.message)
    db.commit()
