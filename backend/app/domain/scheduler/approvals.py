"""定时任务等主人认可的那一版(ADR 0047)。

定时任务到点替主人跑、花主人的 AI 连接和插件连接;而它绑着的工作流是工作区内容,同事能改。所以「这一版要不要
主人担保」和私有账号那条一样(见 domain/authority):被执行的每一版,花谁的钱就要谁担保 —— 判据在
workflows.engine.unvouched_spend,开跑前问它,执行时的闸兜底。这里是定时任务这一侧要做的几件事:

- **点「立即运行」即认可**(D6):主人就在现场,记他为绑着的那张图当前版的担保人;
- **任务上挂「待你确认」**(D10):下一次到点会不会停在「这一版要主人认可」,停的话是哪一版;
- **别人改了图,告诉任务主人**(D10):只提醒、不拦。存出新的一版时(workflows.revisions.on_saved,组装根登记)
  给主人发一条通知;同一个任务已经有一条没读的就不再发 —— 编辑器是自动保存的,改一处就是一版。
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import DEFAULT_LOCALE, t
from app.db.models import Notification, ScheduledTask, User, Workflow, WorkflowRevision
from app.domain.authority import Voucher
from app.domain.references import referrers
from app.domain.scheduler.executors import bound_workflow

#: 通知载荷里 `reminder` 那一格的值:认出这一类提醒(去重用)。
REMINDER = "awaiting_approval"
#: 往上找「谁调用了这张图」最多几层 —— 和执行时 call_workflow 的嵌套上限同一个数。
_MAX_CALLER_DEPTH = 8


def attest_bound_workflow(db: Session, task: ScheduledTask, user_id: str) -> None:
    """点「立即运行」即认可(D6):任务绑着的那张图的当前版,记点的人为担保人。不是工作流任务、图不在了,什么都不做
    (跑不起来的由触发前的检查报)。"""
    from app.domain.workflows.revisions import WorkflowRevisionError, attest_current_revision

    workflow = bound_workflow(db, workspace_id=task.workspace_id, payload=task.payload) if task.kind == "workflow" else None
    if workflow is None:
        return
    try:
        attest_current_revision(db, workflow, attested_by=user_id)
    except WorkflowRevisionError:
        return  # 说不清当前是哪一版:由开跑前那一道报


def awaiting_approval(db: Session, task: ScheduledTask) -> Voucher | None:
    """这个任务下一次到点,会不会停在「这一版要主人认可」:会的话是哪条工作流的哪一版。停用的、不是工作流的不算。"""
    from app.domain.workflows import WorkflowDomainError
    from app.domain.workflows.engine import unvouched_spend

    if task.kind != "workflow" or not task.enabled or not task.owner_user_id:
        return None
    workflow = bound_workflow(db, workspace_id=task.workspace_id, payload=task.payload)
    if workflow is None:
        return None
    try:
        return unvouched_spend(db, workflow, task.owner_user_id)
    except WorkflowDomainError:
        return None  # 图本身跑不起来 —— 那是另一句话(任务启用、触发前的检查报)


def mark_awaiting_approval(db: Session, tasks: list[ScheduledTask]) -> list[ScheduledTask]:
    """给要序列化出去的任务挂上「待你确认」(非映射属性,只为序列化而挂)。"""
    for task in tasks:
        waiting = awaiting_approval(db, task)
        task.awaiting_approval = waiting.attest_details()["attest"] if waiting is not None else None
    return tasks


def tasks_waiting_on(db: Session, workflow: Workflow) -> list[tuple[ScheduledTask, Voucher]]:
    """绑着这张图、或绑着调用它的图(顺着调用关系往上)的启用中的任务里,此刻在等主人认可的那些,和各自等的那一版。"""
    found: list[tuple[ScheduledTask, Voucher]] = []
    for task in _tasks_using(db, workflow):
        waiting = awaiting_approval(db, task)
        if waiting is not None:
            found.append((task, waiting))
    return found


def remind_owners(db: Session, workflow: Workflow, revision: WorkflowRevision) -> None:
    """有人存了 `workflow` 的新一版(workflows.revisions.on_saved):在等主人认可的**别人的**任务,给主人发一条通知。

    主人自己存的不发 —— 他自己的那一版他就是担保人,还在等的是别处(子流程)的那一版,任务卡上看得见。
    同一个任务给主人的这类通知还有一条没读,就不再发。不提交,随存图的那个事务。
    """
    from app.domain.notifications import notify

    saver = revision.created_by
    for task, waiting in tasks_waiting_on(db, workflow):
        owner = task.owner_user_id
        if not owner or owner == saver or _unread_reminder(db, owner, task.id):
            continue
        notify(
            db,
            task.workspace_id,
            user_id=owner,
            type="system",
            title=t("schedNotice_awaitingApproval", DEFAULT_LOCALE, name=task.name),
            body=t(
                "schedNotice_awaitingApprovalBody",
                DEFAULT_LOCALE,
                saver=_display_name(db, saver),
                workflow=waiting.workflow_name,
                revision=waiting.revision,
            ),
            link="#/scheduler",
            payload={"scheduled_task_id": task.id, "reminder": REMINDER, **waiting.attest_details()},
        )


def _tasks_using(db: Session, workflow: Workflow) -> Iterator[ScheduledTask]:
    """绑着这张图的任务,和绑着(字面量)调用它的图的任务 —— 顺着调用关系往上找。按引用表反查(db/references)。"""
    seen = {workflow.id}
    frontier = [workflow.id]
    for _depth in range(_MAX_CALLER_DEPTH + 1):
        if not frontier:
            break
        callers: list[str] = []
        for workflow_id in frontier:
            yield from db.scalars(
                select(ScheduledTask)
                .where(
                    ScheduledTask.workspace_id == workflow.workspace_id,
                    ScheduledTask.kind == "workflow",
                    ScheduledTask.enabled.is_(True),
                    ScheduledTask.id.in_(referrers("workflow", workflow_id, "scheduled_task")),
                )
                .order_by(ScheduledTask.created_at)
            )
            for caller in db.scalars(
                select(Workflow.id).where(
                    Workflow.workspace_id == workflow.workspace_id,
                    Workflow.id.in_(referrers("workflow", workflow_id, "workflow")),
                )
            ):
                if caller not in seen:
                    seen.add(caller)
                    callers.append(caller)
        frontier = callers


def _unread_reminder(db: Session, user_id: str, task_id: str) -> bool:
    return db.scalar(
        select(Notification.id)
        .where(
            Notification.user_id == user_id,
            Notification.read_at.is_(None),
            Notification.payload["scheduled_task_id"].as_string() == task_id,
            Notification.payload["reminder"].as_string() == REMINDER,
        )
        .limit(1)
    ) is not None


def _display_name(db: Session, user_id: str | None) -> str:
    user = db.get(User, user_id) if user_id else None
    return (user.display_name or user.username) if user is not None else "?"
