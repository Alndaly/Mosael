from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas import (
    RunScheduledTaskResponse,
    ScheduledTaskCreate,
    ScheduledTaskOut,
    ScheduledTaskRunOut,
    ScheduledTaskUpdate,
)
from app.db.models import ScheduledTask, ScheduledTaskRun
from app.domain.scheduler import SchedulerBusy, SchedulerDomainError
from app.domain.scheduler import use_cases as scheduler

router = APIRouter(tags=["scheduler"])


@router.post("/scheduled-tasks", response_model=ScheduledTaskOut)
def create_task(body: ScheduledTaskCreate, db: Tx, user: CurrentUser) -> ScheduledTask:
    fields = body.model_dump()
    try:
        return scheduler.create(db, user, fields.pop("workspace_id"), **fields)
    except SchedulerDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/scheduled-tasks", response_model=list[ScheduledTaskOut])
def list_tasks(workspace_id: str, db: DbSession, user: CurrentUser, project_id: str | None = None) -> list[ScheduledTask]:
    return scheduler.list_tasks(db, user, workspace_id, project_id)


@router.patch("/scheduled-tasks/{task_id}", response_model=ScheduledTaskOut)
def update_task(task_id: str, body: ScheduledTaskUpdate, db: Tx, user: CurrentUser) -> ScheduledTask:
    try:
        return scheduler.update(db, user, task_id, body.model_dump(exclude_unset=True))
    except SchedulerDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/scheduled-tasks/{task_id}", status_code=204)
def delete_task(task_id: str, db: Tx, user: CurrentUser) -> Response:
    scheduler.delete(db, user, task_id)
    return Response(status_code=204)


@router.post("/scheduled-tasks/{task_id}/webhook-secret", response_model=ScheduledTaskOut)
def reset_webhook_secret(task_id: str, db: Tx, user: CurrentUser) -> ScheduledTask:
    """重置触发密钥:旧的触发地址立刻失效(泄漏了就点这个)。"""
    try:
        return scheduler.rotate_secret(db, user, task_id)
    except SchedulerDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/scheduled-tasks/{task_id}/runs", response_model=list[ScheduledTaskRunOut])
def list_task_runs(task_id: str, db: DbSession, user: CurrentUser) -> list[ScheduledTaskRun]:
    return scheduler.list_runs(db, user, task_id)


@router.post("/scheduled-tasks/{task_id}/run", response_model=RunScheduledTaskResponse)
def run_task(task_id: str, db: Tx, user: CurrentUser) -> RunScheduledTaskResponse:
    try:
        task, run, job = scheduler.run_now(db, user, task_id)
    except SchedulerBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except SchedulerDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RunScheduledTaskResponse(
        task=ScheduledTaskOut.model_validate(task),
        run=ScheduledTaskRunOut.model_validate(run),
        job=job,
    )
