"""工作流节点里「这次运行替谁用东西」—— 跑的人,加上被执行的每一版图的担保人(见 domain/authority)。

执行器签名是固定的 `(db, workflow, config)`,拿不到调用者;但父 job 上记着这活儿替谁干
(`jobs.current_actor`),而工作流 job 的载荷里钉着它执行的那一版(`workflow_revision_id`,
见 engine.start_workflow_job)。沿父链往上走:`call_workflow` 调起的子流程是一条子 job,
它自己那一版的担保人要算,调用它的那一层也要算 —— 任何一层是同事改过的,都借不到主人的东西。

节点里用私有账号 / 档案 / 本机文件时,`actor=` 传的是这里给的 `Authority`,不是 `current_actor`:
后者只有跑的人,正是此前「借别人的任务用别人的」漏过去的那一半。棘轮:
tests/test_runs_act_with_the_revision_authors_authority.py。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Job, Workflow, WorkflowRevision
from app.domain.authority import Authority, Voucher
from app.domain.jobs import current_parent_job_id
from app.domain.workflows.revisions import revision_vouchers


def _voucher(db: Session, job: Job) -> Voucher:
    payload = job.payload or {}
    revision = db.get(WorkflowRevision, str(payload.get("workflow_revision_id") or "")) if payload.get(
        "workflow_revision_id"
    ) else None
    if revision is None:
        # 说不出执行的是哪一版 —— 没有人为它担保。正常的运行都钉着修订(engine.start_workflow_job),
        # 走到这里的是异常数据:宁可借不到私有资源,也不「不知道是哪一版就放行」。
        return Voucher(
            workflow_id=str(payload.get("workflow_id") or ""),
            workflow_name=str(payload.get("subject") or ""),
            revision=int(payload.get("workflow_revision") or 0),
        )
    workflow = db.get(Workflow, revision.workflow_id)
    return Voucher(
        workflow_id=revision.workflow_id,
        workflow_name=workflow.name if workflow is not None else "",
        revision=revision.revision,
        users=revision_vouchers(db, revision),
    )


def current_authority(db: Session) -> Authority:
    """当前节点所在这次运行的全部授权。不在任何运行里时只有「没有人」—— 一律借不到。"""
    job_id = current_parent_job_id()
    actor: str | None = None
    vouchers: list[Voucher] = []
    first = True
    seen: set[str] = set()
    while job_id and job_id not in seen:
        seen.add(job_id)
        job = db.get(Job, job_id)
        if job is None:
            break
        if first:
            actor, first = job.created_by, False
        # 认修订钉子而不只认 kind:定时任务的包装 job 复用成工作流 job(kind 恰好也是 workflow),
        # 别的包装方式换了 kind 也不该让它那一版逃过担保。
        if job.kind == "workflow" or (job.payload or {}).get("workflow_revision_id"):
            voucher = _voucher(db, job)
            if voucher not in vouchers:
                vouchers.append(voucher)
        job_id = job.parent_job_id
    return Authority(actor=actor, vouchers=tuple(vouchers))
