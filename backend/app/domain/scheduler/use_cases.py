"""定时任务的用例:按任务所在的工作区过闸(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

看任务和运行记录不点名权限;建、改、删、重置密钥、立刻跑一次点名 `schedule`。
定时任务默认共享给工作区(团队基建),列表仍按 sharing 的可见性过滤。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ScheduledTask, ScheduledTaskRun, User
from app.domain import sharing
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm
from app.domain.scheduler import operations as ops

SHARE_KIND = "scheduled_task"
#: 运行记录最多给多少条(最近的在前)。
RUN_LIST_LIMIT = 20


def _task(db: Session, task_id: str) -> ScheduledTask:
    task = db.get(ScheduledTask, task_id)
    if task is None:
        raise NotVisible("Scheduled task not found")
    return task


def schedulable_task(db: Session, user: User, task_id: str) -> ScheduledTask:
    task = _task(db, task_id)
    ensure_workspace_perm(db, user, task.workspace_id, "schedule")
    return task


def annotate(db: Session, user: User, task: ScheduledTask) -> ScheduledTask:
    return sharing.annotate(db, SHARE_KIND, [task], user, task.workspace_id)[0]


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
    return sharing.annotate(db, SHARE_KIND, list(db.scalars(stmt)), user, workspace_id)


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


def create(db: Session, user: User, workspace_id: str, **fields: Any) -> ScheduledTask:
    """记下**它替谁跑**:定时执行没有「当时的操作人」,事后要知道这段自动化是谁挂上去的。"""
    ensure_workspace_perm(db, user, workspace_id, "schedule")
    task = ops.create_scheduled_task(db, workspace_id=workspace_id, **fields)
    sharing.claim(db, SHARE_KIND, task, user)
    db.flush()
    return annotate(db, user, task)


def update(db: Session, user: User, task_id: str, changes: dict[str, Any]) -> ScheduledTask:
    return ops.update_scheduled_task(db, schedulable_task(db, user, task_id), changes)


def delete(db: Session, user: User, task_id: str) -> None:
    task = schedulable_task(db, user, task_id)
    sharing.forget(db, SHARE_KIND, task.id)
    db.delete(task)


def rotate_secret(db: Session, user: User, task_id: str) -> ScheduledTask:
    """重置触发密钥:旧的触发地址立刻失效(泄漏了就点这个)。"""
    return annotate(db, user, ops.rotate_webhook_secret(db, schedulable_task(db, user, task_id)))


def run_now(db: Session, user: User, task_id: str) -> tuple[ScheduledTask, ScheduledTaskRun, Any]:
    task = schedulable_task(db, user, task_id)
    run, job = ops.trigger_scheduled_task(db, task)
    return task, run, job
