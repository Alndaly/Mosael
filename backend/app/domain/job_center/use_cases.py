"""任务中心的用例:谁看得见哪些任务(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看得见 = 工作区的人,**且**看得见任务所属的生成会话(若有):别人私有会话里的生成不列,payload 里就是提示词
(见 domain/generation/sessions)。看不见和不存在同一个回答(404)。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Job, User
from app.domain.generation.sessions import ensure_job_readable, ensure_job_writable, jobs_filter, jobs_writable_filter
from app.domain.jobs import cancel_job, clear_finished_jobs
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm


def list_jobs(
    db: Session, user: User, workspace_id: str, *, kind: str | None = None, top_level: bool = False
) -> list[Job]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(Job).where(Job.workspace_id == workspace_id, jobs_filter(Job.id, user, workspace_id))
    if kind:
        stmt = stmt.where(Job.kind == kind)
    # 任务中心传 top_level:只列顶层任务,工作流派生的子任务(parent_job_id 非空)收到父下,不再平铺。
    if top_level:
        stmt = stmt.where(Job.parent_job_id.is_(None))
    return list(db.scalars(stmt.order_by(Job.created_at.desc())))


def readable(db: Session, user: User, job_id: str) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise NotVisible("Job not found")
    ensure_workspace_access(db, user, job.workspace_id)
    try:
        ensure_job_readable(db, user, job.id)
    except NotVisible:
        # 看不见和不存在同一个回答 —— 连说法都一样,否则措辞本身就泄漏了「它存在」。
        raise NotVisible("Job not found") from None
    return job


def children(db: Session, user: User, job_id: str) -> list[Job]:
    """一个工作流 job 派生的子任务。"""
    parent = readable(db, user, job_id)
    return list(
        db.scalars(
            select(Job)
            .where(Job.parent_job_id == job_id, jobs_filter(Job.id, user, parent.workspace_id))
            .order_by(Job.created_at.asc())
        )
    )


def cancel(db: Session, user: User, job_id: str) -> Job:
    """取消(连同后代)。已经结束的任务取消不了,由 cancel_job 说(ValueError)。"""
    job = readable(db, user, job_id)
    ensure_workspace_perm(db, user, job.workspace_id, "edit")
    ensure_job_writable(db, user, job.id)
    return cancel_job(db, job)


def clear_finished(db: Session, user: User, workspace_id: str) -> int:
    """任务中心的「清空已结束」。别人私有会话里的生成不归他清 —— 和取消同一道闸。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return clear_finished_jobs(db, workspace_id, removable=jobs_writable_filter(Job.id, user))
