"""工作流运行收尾的两件副作用:记这次花了多少、失败时给工作区发通知。

放在 `workflows` 包内、但不是 `engine.py`:引擎只调度节点;计费和通知是运行收尾的用例。
这样 `engine.py` 的顶层 import 不再直接认识 `domain.billing` / `domain.notifications`。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.i18n import tr
from app.db.models import Workflow
from app.domain.billing.usage import run_costs
from app.domain.notifications import notify


def costs_for_job(db: Session, job_id: str) -> dict[str, object]:
    """这次运行(含它派生的子任务)一共花了多少。"""
    return run_costs(db, job_id)


def notify_failure(db: Session, workflow: Workflow, job_id: str, exc: BaseException) -> None:
    """工作流失败:给工作区成员留一条可读通知。标题按**写下这一刻**的请求语言翻。"""
    notify(
        db,
        workflow.workspace_id,
        type="workflow",
        title=tr("jobMsg_workflowFailed", name=workflow.name),
        body=str(exc),
        link="#/workflows",
        payload={"workflow_id": workflow.id, "job_id": job_id},
    )
