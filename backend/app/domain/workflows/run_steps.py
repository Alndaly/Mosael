"""一次运行走到哪了:每个落定的节点记一行,失败或被打断之后从那里接着跑(ADR 0092)。

**为什么不沿用「等人确认」的检查点。** 那份现场在暂停那一刻整份写一次,只有顶层;失败和重启不会预告,所以这里在每个节点
跑完时就记,记的时候和节点自己的工作同一个事务 —— 节点的产物落了库,它的这一行也落了,不会一个有一个没有。循环体里的节点
同样记(`scope` 分层),一条 30 段的循环断在第 20 段,前 19 段一步都不用重做。

**交出去的单接回来。** 节点在等一个子任务时被打断(后端重启),节点没有落定,但那张单还在跑、钱也在花。下单时记下这张单
(`hold`),接着跑时认它,不下第二次单。

**一张单按「要的是什么」认,不按第几张认。** 一个节点可以下好几张单(数字人一块一块改口型、一个资产画几个角度),
而第二遍走到这里时走的路不一定一样:改好的块走缓存,根本不下单,按序号认就会把第一块的单认给第二块。按内容认还顺带答了
另一件事:人调整了参数再继续,这个节点要的东西变了,旧单认不上,就下新单,不会把旧参数的产物当成调整后的结果。
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
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


def forget_from(db: Session, job_id: str, loop_node: str, index: int, downstream: set[str]) -> None:
    """重做:忘掉循环 `loop_node` 第 `index` 轮及之后的步骤、循环自己、和它下游的节点。之前的那几轮留着。"""
    prefix = f"{loop_node}/#"
    rows = db.scalars(select(WorkflowRunStep).where(WorkflowRunStep.job_id == job_id))
    for row in rows:
        here = row.scope == "" and (row.node_id == loop_node or row.node_id in downstream)
        round_text = row.scope[len(prefix):].split("/", 1)[0] if row.scope.startswith(prefix) else ""
        inside = row.scope.split("/", 1)[0] in downstream if row.scope else False
        if here or inside or (round_text.isdigit() and int(round_text) >= index):
            db.delete(row)


def _order_key(what: Any) -> str:
    text = json.dumps(what, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def hold(db: Session, what: Any, job_id: str) -> None:
    """当前节点为 `what` 下了这张单。**不提交**,跟着下单那次事务。不在运行里(直接调执行器)时什么都不做。"""
    run_job_id, node_id = current_parent_job_id(), current_node()
    if not run_job_id or not node_id:
        return
    held = {_order_key(what): job_id}
    row = _row(db, run_job_id, step_scope(), node_id)
    if row is None:
        db.add(WorkflowRunStep(job_id=run_job_id, scope=step_scope(), node_id=node_id, held=held))
        #: 同一个事务里下第二张单、或者节点落定时,都要读得到这一行。
        db.flush()
    else:
        row.held = {**(row.held or {}), **held}


def held_job(db: Session, what: Any) -> Job | None:
    """接着跑时,当前节点上回为 `what` 下的那张单,不管它现在什么状态。"""
    run_job_id, node_id = current_parent_job_id(), current_node()
    if not is_continuing() or not run_job_id or not node_id:
        return None
    row = _row(db, run_job_id, step_scope(), node_id)
    job_id = (row.held or {}).get(_order_key(what)) if row is not None else None
    return db.get(Job, job_id) if job_id else None


def _still_good(job: Job | None) -> bool:
    """失败或被取消的单不算:节点再跑一遍就是要重新下单。"""
    return job is not None and job.status not in ("failed", CANCELLED)


def ordered(db: Session, what: Any, place: Callable[[], str]) -> str:
    """`what` 的那张单:上回下过、还用得上就接回它,否则 `place()` 下一张并记下。交回子任务 id。

    记下的这一行由紧接着的 `wait_for_job(release=db)` 提交。
    """
    job = held_job(db, what)
    if _still_good(job):
        return job.id
    job_id = place()
    hold(db, what, job_id)
    return job_id


def held_generation(db: Session, what: Any) -> tuple[str, str] | None:
    """接着跑时,`what` 那张还用得上的生成单:(生成记录 id, 子任务 id)。生成要在下单的事务里记,走不了 `ordered`。"""
    job = held_job(db, what)
    if not _still_good(job):
        return None
    generation = db.scalar(select(GenerationJob).where(GenerationJob.job_id == job.id))
    return (generation.id, job.id) if generation is not None else None


__all__ = ["forget_from", "held_generation", "held_job", "hold", "ordered", "record", "recorded"]
