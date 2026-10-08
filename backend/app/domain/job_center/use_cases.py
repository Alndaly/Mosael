"""任务中心的用例:谁看得见哪些任务(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看得见 = 工作区的人,**且**看得见任务所属的生成会话(若有):别人私有会话里的生成不列,payload 里就是提示词
(见 domain/generation/sessions)。看不见和不存在同一个回答(404)。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import GenerationJob, Job, User
from app.domain.generation.sessions import ensure_job_readable, ensure_job_writable, jobs_filter, jobs_writable_filter
from app.core.unit_of_work import unit_of_work
from app.domain.jobs import DELETE_JOBS_BATCH, TERMINAL_STATUSES, cancel_job, delete_jobs, plan_clear_finished
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm


#: 列表默认给最近这么多条(另加全部还在跑的)。任务中心收拢之后只摆十来行已结束的,定时任务页按 id 找还在跑的那几条。
LIST_LIMIT = 200


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
    return cancel_job(db, job)


def clear_finished(db: Session, user: User, workspace_id: str) -> int:
    """任务中心的「清空已结束」。别人私有会话里的生成不归他清 —— 和取消同一道闸。

    **一批一个事务**:先读出该删的(不占写锁),再按 DELETE_JOBS_BATCH 个一批删、每批提交。一个用了几个月的工作区有上万个
    已结束任务,一个事务删完要攥着写锁十几秒,那期间别的写入(任务进度、别人的请求)5 秒后报 database is locked。
    清理是幂等的:中途失败,删掉的那几批就是删掉了,剩下的下次再点;拆开的一棵树里留下的子任务没了父任务,下次当顶层清。
    `db` 只用来读和鉴权,删走自己的事务。
    """
    ensure_workspace_perm(db, user, workspace_id, "edit")
    doomed = plan_clear_finished(db, workspace_id, removable=jobs_writable_filter(Job.id, user)).ids()
    removed = 0
    for start in range(0, len(doomed), DELETE_JOBS_BATCH):
        with unit_of_work() as batch:
            removed += delete_jobs(batch, doomed[start:start + DELETE_JOBS_BATCH])
    return removed


def preview_clear_finished(db: Session, user: User, workspace_id: str) -> dict[str, int]:
    """点「清空已结束」之前先给他看:会删几条(连同子任务几个)、其中几条是别人发起的、留下几条。

    和 `clear_finished` 同一份计划、同一道闸 —— 看到的数和真删的数是同一个。
    """
    ensure_workspace_perm(db, user, workspace_id, "edit")
    plan = plan_clear_finished(db, workspace_id, removable=jobs_writable_filter(Job.id, user))
    return {
        "tasks": len(plan.trees),
        "jobs": sum(len(nodes) for nodes in plan.trees),
        "by_others": sum(
            1 for nodes in plan.trees if any(node.created_by not in (None, user.id) for node in nodes)
        ),
        "kept": plan.kept,
    }
