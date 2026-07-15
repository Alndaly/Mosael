from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.schemas import (
    RunScheduledTaskResponse,
    ScheduledTaskCreate,
    ScheduledTaskOut,
    ScheduledTaskRunOut,
    ScheduledTaskUpdate,
)
from app.db.models import ScheduledTask
from app.domain.scheduler import create_scheduled_task, run_scheduled_task, update_scheduled_task
from app.domain.scheduler.operations import SchedulerDomainError

router = APIRouter(tags=["scheduler"])


@router.post("/scheduled-tasks", response_model=ScheduledTaskOut)
def create_task(body: ScheduledTaskCreate, db: DbSession) -> ScheduledTask:
    try:
        return create_scheduled_task(db, **body.model_dump())
    except SchedulerDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/scheduled-tasks", response_model=list[ScheduledTaskOut])
def list_tasks(workspace_id: str, db: DbSession, project_id: str | None = None) -> list[ScheduledTask]:
    stmt = select(ScheduledTask).where(ScheduledTask.workspace_id == workspace_id)
    if project_id:
        stmt = stmt.where(ScheduledTask.project_id == project_id)
    stmt = stmt.order_by(ScheduledTask.created_at.desc())
    return list(db.scalars(stmt))


@router.patch("/scheduled-tasks/{task_id}", response_model=ScheduledTaskOut)
def update_task(task_id: str, body: ScheduledTaskUpdate, db: DbSession) -> ScheduledTask:
    task = _get_task(db, task_id)
    try:
        return update_scheduled_task(db, task, body.model_dump(exclude_unset=True))
    except SchedulerDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/scheduled-tasks/{task_id}", status_code=204)
def delete_task(task_id: str, db: DbSession) -> Response:
    task = _get_task(db, task_id)
    db.delete(task)
    db.commit()
    return Response(status_code=204)


@router.post("/scheduled-tasks/{task_id}/run", response_model=RunScheduledTaskResponse)
def run_task(task_id: str, db: DbSession) -> RunScheduledTaskResponse:
    task = _get_task(db, task_id)
    try:
        run, job = run_scheduled_task(db, task)
    except SchedulerDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
