"""任务中心的用例:谁看得见哪些任务(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看得见 = 工作区的人,**且**看得见任务所属的生成会话(若有):别人私有会话里的生成不列,payload 里就是提示词
(见 domain/generation/sessions)。看不见和不存在同一个回答(404)。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.models import GenerationJob, Job, JobCenterMark, User, now
from app.domain.generation.sessions import ensure_job_readable, ensure_job_writable, jobs_filter
from app.domain.jobs import TERMINAL_STATUSES, cancel_job
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_member, ensure_workspace_perm


#: 列表默认给最近这么多条(另加全部还在跑的)。定时任务页按 id 找运行记录挂着的那几条。
LIST_LIMIT = 200
#: 任务中心面板给最近这么多条(另加全部还在跑的):面板收拢之后只摆十来行已结束的。
PANEL_LIMIT = 200


def list_jobs(
    db: Session, user: User, workspace_id: str, *, kind: str | None = None, top_level: bool = False,
    recorded: bool = False, limit: int = LIST_LIMIT,
) -> list[Job]:
    """最近的 `limit` 条,**加上全部还在跑的**(排队中、运行中),新的在前。

    此前不设上限:一个用了几个月的工作区有上千个任务,有任务在跑时任务中心每 1.5 秒拉一遍整表。还在跑的不受上限
    限制 —— 一个跑了一整夜的批量任务排在两百条之后,也得看得见它的进度、停得下它。
    """
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(Job).where(Job.workspace_id == workspace_id, jobs_filter(Job.id, user, workspace_id))
    if kind:
        stmt = stmt.where(Job.kind == kind)
    if recorded:
        #: 挂着创作记录的(生成、创作页的语音和播客,ADR 0055):创作页只要这些的进度。
        stmt = stmt.where(Job.id.in_(
            select(GenerationJob.job_id).where(GenerationJob.workspace_id == workspace_id, GenerationJob.job_id.is_not(None))
        ))
    # 任务中心传 top_level:只列顶层任务,工作流派生的子任务(parent_job_id 非空)收到父下,不再平铺。
    if top_level:
        stmt = stmt.where(Job.parent_job_id.is_(None))
    newest_first = (Job.created_at.desc(), Job.id.desc())
    recent = list(db.scalars(stmt.order_by(*newest_first).limit(limit)))
    seen = {job.id for job in recent}
    running = [job for job in db.scalars(stmt.where(Job.status.not_in(TERMINAL_STATUSES)).order_by(*newest_first))
               if job.id not in seen]
    return sorted([*recent, *running], key=lambda job: (job.created_at, job.id), reverse=True)


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
    return cancel_job(db, job, by=user.id)


def _mark(db: Session, user: User, workspace_id: str) -> JobCenterMark | None:
    return db.get(JobCenterMark, (user.id, workspace_id))


def panel(
    db: Session, user: User, workspace_id: str, *, cleared: bool = False, limit: int = PANEL_LIMIT,
) -> tuple[list[Job], datetime | None]:
    """任务中心面板上列什么(ADR 0050):顶层任务里**还在跑的全部**,加上结束在我的水位线之后的最近 `limit` 条。

    `cleared`:「显示已清掉的」—— 结束在水位线之前的那些,最近 `limit` 条,只是翻看(D28)。没清过就没有。
    和 `list_jobs` 同一道「看得见」的闸(别人私有会话里的生成不列)。交回 `(任务, 我的水位线)`,界面据水位线决定摆不摆那个开关。
    """
    ensure_workspace_access(db, user, workspace_id)
    mark = _mark(db, user, workspace_id)
    cleared_at = mark.cleared_at if mark is not None else None
    stmt = select(Job).where(
        Job.workspace_id == workspace_id, Job.parent_job_id.is_(None), jobs_filter(Job.id, user, workspace_id)
    )
    finished = Job.status.in_(TERMINAL_STATUSES)
    newest_first = (Job.created_at.desc(), Job.id.desc())
    if cleared:
        if cleared_at is None:
            return [], None
        return list(db.scalars(stmt.where(finished, Job.updated_at <= cleared_at).order_by(*newest_first).limit(limit))), cleared_at
    if cleared_at is not None:
        stmt = stmt.where(or_(~finished, Job.updated_at > cleared_at))
    recent = list(db.scalars(stmt.order_by(*newest_first).limit(limit)))
    seen = {job.id for job in recent}
    running = [job for job in db.scalars(stmt.where(~finished).order_by(*newest_first)) if job.id not in seen]
    return sorted([*recent, *running], key=lambda job: (job.created_at, job.id), reverse=True), cleared_at


def clear_panel(db: Session, user: User, workspace_id: str) -> datetime:
    """「清空已结束」:把我在这个工作区的水位线挪到现在(D27)。**只动我自己的面板**,什么都不删 —— 所以只读成员也能清,
    也不需要确认框(要找回来,打开「显示已清掉的」)。交回新的水位线。"""
    ensure_workspace_member(db, user, workspace_id)
    moment = now()
    mark = _mark(db, user, workspace_id)
    if mark is None:
        db.add(JobCenterMark(user_id=user.id, workspace_id=workspace_id, cleared_at=moment))
    else:
        mark.cleared_at = moment
    db.flush()
    return moment
