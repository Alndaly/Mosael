from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import JobOut, TaskEventOut
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import Job, TaskEvent
from app.domain.jobs import cancel_job, clear_finished_jobs

router = APIRouter(tags=["jobs"])


@router.get("/jobs", response_model=list[JobOut])
def list_jobs(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    kind: str | None = None,
    top_level: bool = False,
) -> list[Job]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(Job).where(Job.workspace_id == workspace_id)
    if kind:
        stmt = stmt.where(Job.kind == kind)
    # 任务中心传 top_level=true:只列顶层任务,工作流派生的子任务(parent_job_id 非空)收到父下,
    # 不再平铺。按 kind 过滤的其它视图(如 AI Studio 生成历史)不传,仍能看到工作流内生成的产物。
    if top_level:
        stmt = stmt.where(Job.parent_job_id.is_(None))
    stmt = stmt.order_by(Job.created_at.desc())
    return list(db.scalars(stmt))


@router.delete("/jobs/finished")
def delete_finished_jobs(workspace_id: str, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return {"removed": clear_finished_jobs(db, workspace_id)}


@router.get("/jobs/{job_id}", response_model=JobOut)
def get_job(job_id: str, db: DbSession, user: CurrentUser) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    ensure_workspace_access(db, user, job.workspace_id)
    return job


@router.get("/jobs/{job_id}/children", response_model=list[JobOut])
def list_job_children(job_id: str, db: DbSession, user: CurrentUser) -> list[Job]:
    """一个工作流 job 派生的子任务(发布/导出/转写/生成/配音)。任务详情里「收纳」展示。"""
    parent = db.get(Job, job_id)
    if parent is None:
        raise HTTPException(status_code=404, detail="Job not found")
    ensure_workspace_access(db, user, parent.workspace_id)
    stmt = select(Job).where(Job.parent_job_id == job_id).order_by(Job.created_at.asc())
    return list(db.scalars(stmt))


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job_route(job_id: str, db: DbSession, user: CurrentUser) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    ensure_workspace_perm(db, user, job.workspace_id, "edit")
    try:
        return cancel_job(db, job)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/jobs/{job_id}/events", response_model=list[TaskEventOut])
def list_job_events(job_id: str, db: DbSession, user: CurrentUser, limit: int = 500) -> list[TaskEvent]:
    """一次运行的事件流(按时间正序)。

    上限按**最早**截断,不是最新 30 条。工作流详情靠 workflow.node.started / finished 配对还原
    每个节点的状态,取最新 N 条会把早期的 started 挤掉 —— 表现为「旧任务只剩最后一个节点、
    前面的步骤全没了」,而最后那个节点因为丢了 started 反而显示成一直在跑。
    """
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    ensure_workspace_access(db, user, job.workspace_id)
    events = list(
        db.scalars(
            select(TaskEvent)
            .where(TaskEvent.job_id == job_id)
            .order_by(TaskEvent.created_at.asc())
            .limit(max(1, min(limit, 2000)))
        )
    )
    return events
