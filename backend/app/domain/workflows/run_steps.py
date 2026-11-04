"""一次运行走到哪了:每个落定的节点记一行,失败或被打断之后从那里接着跑(ADR 0092)。

**为什么不沿用「等人确认」的检查点。** 那份现场在暂停那一刻整份写一次,只有顶层;失败和重启不会预告,所以这里在每个节点
跑完时就记,记的时候和节点自己的工作同一个事务 —— 节点的产物落了库,它的这一行也落了,不会一个有一个没有。循环体里的节点
同样记(`scope` 分层),一条 30 段的循环断在第 20 段,前 19 段一步都不用重做。

**交出去的生成任务接回来。** 节点在等一个生成任务时被打断(后端重启),节点没有落定,但那张单还在跑、钱也在花。
下单的同一个事务里记下这张单(`hold`),接着跑时认它,不下第二次单。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import GenerationJob, Job, WorkflowRunStep
from app.domain.jobs import CANCELLED, current_parent_job_id
from app.domain.workflows.run_scope import current_node, is_continuing, step_scope

logger = logging.getLogger(__name__)


def _row(db: Session, job_id: str, scope: str, node_id: str) -> WorkflowRunStep | None:
    return db.scalar(select(WorkflowRunStep).where(
        WorkflowRunStep.job_id == job_id, WorkflowRunStep.scope == scope, WorkflowRunStep.node_id == node_id,
    ))


def record(db: Session, job_id: str, scope: str, node_id: str, outputs: Any) -> None:
    """这个节点落定了。**不提交**,跟着节点自己那次事务。

    产物存不成 JSON 的(执行器交回了别的东西)不记:接着跑时它重做一遍,比为一次记录把跑成功的节点弄失败好。
    """
    try:
        json.dumps(outputs)
    except (TypeError, ValueError):
        logger.warning("workflow run %s: node %s outputs are not JSON, it would run again on continue", job_id, node_id)
        return
    row = _row(db, job_id, scope, node_id)
    if row is None:
        db.add(WorkflowRunStep(job_id=job_id, scope=scope, node_id=node_id, outputs=outputs))
    else:
        row.outputs, row.held = outputs, None


def recorded(db: Session, job_id: str, scope: str) -> dict[str, Any]:
    """这一层图里已经落定的节点:节点 id → 产物。"""
    rows = db.scalars(select(WorkflowRunStep).where(
        WorkflowRunStep.job_id == job_id, WorkflowRunStep.scope == scope, WorkflowRunStep.outputs.is_not(None),
    ))
    return {row.node_id: row.outputs for row in rows if row.outputs is not None}


def forget(db: Session, job_id: str) -> None:
    """运行成功了,这些记录用不上了。"""
    db.execute(delete(WorkflowRunStep).where(WorkflowRunStep.job_id == job_id))


def hold_generation(db: Session, generation_id: str, child_job_id: str) -> None:
    """当前节点把这张生成单交了出去。**不提交**,和下单同一个事务:单落了库,这一行也落了。不在运行里(直接调执行器)时什么都不做。"""
    job_id, node_id = current_parent_job_id(), current_node()
    if not job_id or not node_id:
        return
    held = {"generation_id": generation_id, "job_id": child_job_id}
    row = _row(db, job_id, step_scope(), node_id)
    if row is None:
        db.add(WorkflowRunStep(job_id=job_id, scope=step_scope(), node_id=node_id, held=held))
    else:
        row.held = held


def held_generation(db: Session) -> tuple[str, str] | None:
    """接着跑时,当前节点上回交出去、还用得上的那张单:(生成记录 id, 子任务 id)。

    失败或被取消的单不算:节点再跑一遍就是要重新下单。
    """
    job_id, node_id = current_parent_job_id(), current_node()
    if not is_continuing() or not job_id or not node_id:
        return None
    row = _row(db, job_id, step_scope(), node_id)
    held = row.held if row is not None else None
    if not held:
        return None
    child = db.get(Job, held["job_id"])
    if child is None or child.status in ("failed", CANCELLED) or db.get(GenerationJob, held["generation_id"]) is None:
        return None
    return held["generation_id"], held["job_id"]


__all__ = ["forget", "held_generation", "hold_generation", "record", "recorded"]
