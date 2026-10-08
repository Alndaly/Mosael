"""定时任务的用例:按任务所在的工作区过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看任务和运行记录不点名权限;建任务点名 `schedule`。定时任务默认共享给工作区(团队基建),列表仍按 sharing 的
可见性过滤。

**管一个任务只有它的主人**(改、停用 / 启用、删、重置触发密钥、立即运行):任务到点替主人跑、用主人的钥匙和额度
(见 operations._open_run),和发布账号、浏览器档案是同一类东西 —— 共享进工作区是借给同事看、看它跑得怎样,
不是交出去管(ADR 0008 §3.9,`sharing.ensure_manageable`)。此前只查 editor:同事能把别人的任务改绑到自己的
工作流、再点「立即运行」,用别人的钥匙和额度跑自己的东西。

触发密钥只存哈希;原文只出现在生成它的那一次响应里(建 webhook 任务、重置密钥、改成 webhook),由这几个用例
连同任务一起交给路由。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ScheduledTask, ScheduledTaskRun, User, Workflow
from app.domain import sharing
from app.domain.authority import Voucher
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm
from app.domain.scheduler import approvals
from app.domain.scheduler import operations as ops

SHARE_KIND = "scheduled_task"
#: 运行记录最多给多少条(最近的在前)。
RUN_LIST_LIMIT = 20


def _task(db: Session, task_id: str) -> ScheduledTask:
    task = db.get(ScheduledTask, task_id)
    if task is None:
        raise NotVisible("Scheduled task not found")
    return task


def manageable_task(db: Session, user: User, task_id: str) -> ScheduledTask:
    """要管这个任务:工作区里有 `schedule` 权限,**而且是任务的主人**(见模块说明)。"""
    task = _task(db, task_id)
    ensure_workspace_perm(db, user, task.workspace_id, "schedule")
    sharing.ensure_manageable(db, SHARE_KIND, task, actor=user.id)
    return task


def annotate(db: Session, user: User, task: ScheduledTask) -> ScheduledTask:
    return _annotated(db, user, [task], task.workspace_id)[0]


def _annotated(db: Session, user: User, tasks: list[ScheduledTask], workspace_id: str) -> list[ScheduledTask]:
    """是不是我的、在不在工作区里(sharing),加上「待你确认」:下一次到点会不会停在「这一版要主人认可」(ADR 0047)。"""
    return approvals.mark_awaiting_approval(db, sharing.annotate(db, SHARE_KIND, tasks, user, workspace_id))


# ---------------- 读 ----------------


def list_tasks(db: Session, user: User, workspace_id: str, project_id: str | None = None) -> list[ScheduledTask]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(ScheduledTask).where(
        ScheduledTask.workspace_id == workspace_id,
        sharing.visible_filter(SHARE_KIND, user, workspace_id),
    )
    if project_id:
        stmt = stmt.where(ScheduledTask.project_id == project_id)
    stmt = stmt.order_by(ScheduledTask.created_at.desc())
    return _annotated(db, user, list(db.scalars(stmt)), workspace_id)


def awaiting_approval_for(db: Session, user: User, workflow: Workflow) -> list[tuple[ScheduledTask, Voucher]]:
    """绑着这张图(或调用它的图)、此刻在等主人认可的任务,只给这个人看得见的那些 —— 编辑器据此提醒改图的人
    「你存的这一版要 A 认可之后,A 的任务才会接着跑」(ADR 0047 D10)。调用方已经确认他能看这张图。"""
    visible = set(db.scalars(select(ScheduledTask.id).where(sharing.visible_filter(SHARE_KIND, user, workflow.workspace_id))))
    return [(task, waiting) for task, waiting in approvals.tasks_waiting_on(db, workflow) if task.id in visible]


def list_runs(db: Session, user: User, task_id: str) -> list[ScheduledTaskRun]:
    task = _task(db, task_id)
    ensure_workspace_access(db, user, task.workspace_id)
    return list(
        db.scalars(
            select(ScheduledTaskRun)
            .where(ScheduledTaskRun.scheduled_task_id == task_id)
            .order_by(ScheduledTaskRun.started_at.desc())
            .limit(RUN_LIST_LIMIT)
        )
    )


# ---------------- 写 ----------------


def create(db: Session, user: User, workspace_id: str, **fields: Any) -> tuple[ScheduledTask, str | None]:
    """记下**它替谁跑**:定时执行没有「当时的操作人」,事后要知道这段自动化是谁挂上去的。

    webhook 任务连同触发密钥的原文一起返回(只这一次,见 operations.issue_webhook_secret);别的任务给 None。
    """
    ensure_workspace_perm(db, user, workspace_id, "schedule")
    task = ops.create_scheduled_task(db, workspace_id=workspace_id, owner=user.id, **fields)
    sharing.claim(db, SHARE_KIND, task, user)
    secret = ops.issue_webhook_secret(db, task) if task.trigger_type == "webhook" else None
    db.flush()
    return annotate(db, user, task), secret


def update(db: Session, user: User, task_id: str, changes: dict[str, Any]) -> tuple[ScheduledTask, str | None]:
    """改一个任务。改成 webhook 任务时发一把新密钥,原文随这一次返回。"""
    task = ops.update_scheduled_task(db, manageable_task(db, user, task_id), changes)
    secret = ops.issue_webhook_secret(db, task) if task.trigger_type == "webhook" and not task.webhook_secret_hash else None
    return annotate(db, user, task), secret


def delete(db: Session, user: User, task_id: str) -> None:
    task = manageable_task(db, user, task_id)
    sharing.forget(db, "scheduled_task", task.id)
    db.delete(task)


def rotate_secret(db: Session, user: User, task_id: str) -> tuple[ScheduledTask, str]:
    """重置触发密钥:旧的触发地址立刻失效(泄漏了就点这个)。新密钥的原文只随这一次返回。"""
    task = manageable_task(db, user, task_id)
    secret = ops.rotate_webhook_secret(db, task)
    return annotate(db, user, task), secret


def run_now(db: Session, user: User, task_id: str) -> tuple[ScheduledTask, ScheduledTaskRun, Any]:
    task = manageable_task(db, user, task_id)
    #: 点「立即运行」即认可(ADR 0047 D6):主人就在现场,有人看着的这一次不该停在「这一版要你认可」。
    approvals.attest_bound_workflow(db, task, user.id)
    run, job = ops.trigger_scheduled_task(db, task)
    return annotate(db, user, task), run, job
