from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.domain import sharing
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    RunScheduledTaskResponse,
    ScheduledTaskCreate,
    ScheduledTaskOut,
    ScheduledTaskRunOut,
    ScheduledTaskUpdate,
)
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import ScheduledTask, ScheduledTaskRun
from app.domain.scheduler import create_scheduled_task, run_scheduled_task, update_scheduled_task
from app.domain.scheduler.operations import SchedulerDomainError

router = APIRouter(tags=["scheduler"])


@router.post("/scheduled-tasks", response_model=ScheduledTaskOut)
def create_task(body: ScheduledTaskCreate, db: DbSession, user: CurrentUser) -> ScheduledTask:
    ensure_workspace_perm(db, user, body.workspace_id, "schedule")
    try:
        task = create_scheduled_task(db, **body.model_dump())
    except SchedulerDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # 记下**它替谁跑**。定时任务默认共享给工作区(团队基建),归属是为了可追溯:定时执行没有
    # "当时的操作人",而事后要知道这段自动化是谁挂上去的。
    sharing.claim(db, "scheduled_task", task, user)
    db.commit()
    return sharing.annotate(db, "scheduled_task", [task], user, task.workspace_id)[0]


@router.get("/scheduled-tasks", response_model=list[ScheduledTaskOut])
def list_tasks(workspace_id: str, db: DbSession, user: CurrentUser, project_id: str | None = None) -> list[ScheduledTask]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(ScheduledTask).where(
        ScheduledTask.workspace_id == workspace_id,
        sharing.visible_filter("scheduled_task", user, workspace_id),
    )
    if project_id:
        stmt = stmt.where(ScheduledTask.project_id == project_id)
    stmt = stmt.order_by(ScheduledTask.created_at.desc())
    return sharing.annotate(db, "scheduled_task", list(db.scalars(stmt)), user, workspace_id)


@router.patch("/scheduled-tasks/{task_id}", response_model=ScheduledTaskOut)
def update_task(task_id: str, body: ScheduledTaskUpdate, db: DbSession, user: CurrentUser) -> ScheduledTask:
    task = _get_task(db, task_id)
    ensure_workspace_perm(db, user, task.workspace_id, "schedule")
    try:
        return update_scheduled_task(db, task, body.model_dump(exclude_unset=True))
    except SchedulerDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/scheduled-tasks/{task_id}", status_code=204)
def delete_task(task_id: str, db: DbSession, user: CurrentUser) -> Response:
    task = _get_task(db, task_id)
    ensure_workspace_perm(db, user, task.workspace_id, "schedule")
    sharing.forget(db, "scheduled_task", task.id)
    db.delete(task)
    db.commit()
    return Response(status_code=204)


@router.get("/scheduled-tasks/{task_id}/runs", response_model=list[ScheduledTaskRunOut])
def list_task_runs(task_id: str, db: DbSession, user: CurrentUser) -> list[ScheduledTaskRun]:
    task = db.get(ScheduledTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    ensure_workspace_access(db, user, task.workspace_id)
    return list(
        db.scalars(
            select(ScheduledTaskRun)
            .where(ScheduledTaskRun.scheduled_task_id == task_id)
            .order_by(ScheduledTaskRun.started_at.desc())
            .limit(20)
        )
    )


@router.post("/scheduled-tasks/{task_id}/run", response_model=RunScheduledTaskResponse)
def run_task(task_id: str, db: DbSession, user: CurrentUser) -> RunScheduledTaskResponse:
    task = _get_task(db, task_id)
    ensure_workspace_perm(db, user, task.workspace_id, "schedule")
    try:
        run, job = run_scheduled_task(db, task)
    except SchedulerDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    from app.workers.scheduler import dispatch_job_for_task

    dispatch_job_for_task(db, task, run, job)
    return RunScheduledTaskResponse(
        task=ScheduledTaskOut.model_validate(task),
        run=ScheduledTaskRunOut.model_validate(run),
        job=job,
    )


def _get_task(db, task_id: str) -> ScheduledTask:
    task = db.get(ScheduledTask, task_id)
    if task is None:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return task
