"""批量执行器:同一工作流按参数行顺序跑 N 次。

顺序执行是有意为之 —— 单机 ffmpeg/AI 供应商都吃不住并发轰炸
(计划 §"批量并发上限" v1 取 1)。父 job 聚合进度,子 job 逐项
落任务中心;单项失败不打断整批,最终结果统计成功/失败数。
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import BatchRun, Job, TaskEvent, Workflow
from app.domain.jobs import create_job
from app.domain.notifications import notify
from app.domain.workflows import WorkflowDomainError, validate_graph
from app.domain.workflows.engine import run_workflow

logger = logging.getLogger(__name__)


def start_batch(
    db: Session,
    *,
    workspace_id: str,
    workflow: Workflow,
    name: str,
    params_list: list[dict[str, Any]],
) -> BatchRun:
    if not params_list:
        raise WorkflowDomainError("批量至少需要一行参数")
    errors = validate_graph(workflow.graph)
    if errors:
        raise WorkflowDomainError("；".join(errors))

    parent = create_job(
        db,
        workspace_id=workspace_id,
        kind="batch",
        payload={"workflow_id": workflow.id, "items": len(params_list)},
        message=f"批量排队中: {name}",
    )
    batch = BatchRun(
        workspace_id=workspace_id,
        workflow_id=workflow.id,
        name=name,
        params_list=params_list,
        job_id=parent.id,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    # 回填 batch_id,任务中心/通知从 job 一步深链到这条批量记录。
    parent.payload = {**parent.payload, "batch_id": batch.id}
    db.commit()
    threading.Thread(target=_run_batch_thread, args=(batch.id,), daemon=True).start()
    return batch


def _run_batch_thread(batch_id: str) -> None:
    with SessionLocal() as db:
        batch = db.get(BatchRun, batch_id)
        if batch is None or batch.job_id is None:
            return
        parent = db.get(Job, batch.job_id)
        workflow = db.get(Workflow, batch.workflow_id)
        if parent is None or workflow is None:
            return

        total = len(batch.params_list)
        succeeded = 0
        failed = 0
        parent.status = "running"
        parent.message = f"批量运行中: {batch.name} (0/{total})"
        db.commit()

        for index, params in enumerate(batch.params_list):
            # 父 job 被取消 → 不再开新的子项(在跑的那一项在其节点边界自行停止)。
            db.refresh(parent)
            if parent.status == "failed":
                return

            item_job = create_job(
                db,
                workspace_id=batch.workspace_id,
                kind="workflow",
                payload={"workflow_id": workflow.id, "batch_id": batch.id, "batch_index": index, "params": params},
                message=f"{batch.name} · #{index + 1}",
            )
            batch.item_job_ids = [*batch.item_job_ids, item_job.id]
            db.commit()
            try:
                run_workflow(db, workflow, item_job, dict(params or {}))
                succeeded += 1
            except Exception as exc:  # noqa: BLE001 — 单项失败不打断整批
                logger.exception("Batch %s item %d failed", batch_id, index)
                item_job.status = "failed"
                item_job.error = str(exc)[:500]
                item_job.message = f"{batch.name} · #{index + 1} 失败"
                db.add(TaskEvent(job_id=item_job.id, type="workflow.failed", payload={"error": str(exc)[:500]}))
                failed += 1
            parent.progress = (index + 1) / total
            parent.message = f"批量运行中: {batch.name} ({index + 1}/{total})"
            db.commit()

        parent.status = "succeeded" if failed == 0 else ("failed" if succeeded == 0 else "succeeded")
        parent.progress = 1.0
        parent.result = {"succeeded": succeeded, "failed": failed, "total": total}
        parent.message = f"批量完成: {batch.name}(成功 {succeeded} / 失败 {failed})"
        notify(
            db,
            batch.workspace_id,
            type="batch",
            title=f"批量完成: {batch.name}",
            body=f"成功 {succeeded} / 失败 {failed}(共 {total} 项)",
            link="#/batch",
            payload={"batch_id": batch.id, "succeeded": succeeded, "failed": failed},
        )
        db.commit()


def batch_with_items(db: Session, batch: BatchRun) -> dict[str, Any]:
    """列表/详情共用的展开:父 job 状态 + 每项子 job 状态。"""
    parent = db.get(Job, batch.job_id) if batch.job_id else None
    jobs = {
        job.id: job
        for job in db.scalars(select(Job).where(Job.id.in_(batch.item_job_ids))).all()
    }
    items = []
    for index, params in enumerate(batch.params_list):
        job = jobs.get(batch.item_job_ids[index]) if index < len(batch.item_job_ids) else None
        items.append(
            {
                "index": index,
                "params": params,
                "job_id": job.id if job else None,
                "status": job.status if job else "pending",
                "progress": job.progress if job else 0.0,
                "error": job.error if job else None,
            }
        )
    return {
        "id": batch.id,
        "workspace_id": batch.workspace_id,
        "workflow_id": batch.workflow_id,
        "name": batch.name,
        "status": parent.status if parent else "queued",
        "progress": parent.progress if parent else 0.0,
        "job_id": batch.job_id,
        "created_at": batch.created_at,
        "items": items,
    }
