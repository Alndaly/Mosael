"""工作流执行引擎:依赖驱动的并行 DAG 调度,进度与结果写任务总线。

引擎是纯调度器——拓扑排序、并行调度、条件分支路由、取消边界、事件与进度。
节点**行为**全部在执行器注册表(executors/)里;引擎对具体领域零 import,
新增节点类型不需要改这里。

引擎本身跑在独立线程里;内部再用线程池,前驱都完成的节点即可运行,彼此独立的
分支**同时**跑(节点多为 I/O 型:LLM/HTTP/子任务)。每个节点产生
workflow.node.started / finished 事件,job.progress 按已完成节点数推进;节点输出
写入上下文供后续节点用 {{节点id.键}} 引用或数据边绑定。
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import Job, TaskEvent, Workflow
from app.domain.jobs import create_job
from app.domain.notifications import notify
from app.domain.workflows import (
    NODE_TYPES,
    WorkflowDomainError,
    topo_order,
    validate_graph,
)
from app.domain.workflows.binding import apply_data_edges, interpolate_node_config
from app.domain.workflows.executors import get_executor

logger = logging.getLogger(__name__)

MAX_PARALLEL_NODES = 8


def start_workflow_job(
    db: Session, workflow: Workflow, *, params: dict[str, Any] | None = None, job: Job | None = None
) -> Job:
    """创建(或复用)workflow job 并启动执行线程。"""
    errors = validate_graph(workflow.graph)
    if errors:
        raise WorkflowDomainError("；".join(errors))
    if job is None:
        job = create_job(
            db,
            workspace_id=workflow.workspace_id,
            kind="workflow",
            payload={"workflow_id": workflow.id, "params": params or {}},
            message=f"工作流排队中: {workflow.name}",
        )
        db.commit()
    threading.Thread(
        target=_run_workflow_thread,
        args=(workflow.id, job.id, params or {}),
        daemon=True,
    ).start()
    return job


def _run_workflow_thread(workflow_id: str, job_id: str, params: dict[str, Any]) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        workflow = db.get(Workflow, workflow_id)
        if job is None or workflow is None:
            return
        try:
            run_workflow(db, workflow, job, params)
        except Exception as exc:  # noqa: BLE001 — 线程内兜底,失败必须落到 job 上
            logger.exception("Workflow %s failed", workflow_id)
            job.status = "failed"
            job.error = str(exc)[:500]
            job.message = "工作流失败"
            db.add(TaskEvent(job_id=job.id, type="workflow.failed", payload={"error": str(exc)[:500]}))
            notify(
                db,
                workflow.workspace_id,
                type="workflow",
                title=f"工作流失败: {workflow.name}",
                body=str(exc)[:300],
                link="#/workflows",
                payload={"workflow_id": workflow.id, "job_id": job.id},
            )
            db.commit()


def run_workflow(db: Session, workflow: Workflow, job: Job, params: dict[str, Any]) -> dict[str, Any]:
    """依赖驱动的并行执行:一个节点的全部前驱都完成后才可运行,彼此独立的分支**同时**跑
    (线程池,节点多为 I/O 型:LLM / HTTP / 子任务)。

    分支语义不变:条件节点把 true/false 写进 result,出边按 source_handle 匹配才算活跃;
    未被任何活跃入边触达的节点整段跳过(Dify 语义)。编排(调度 + 事件 + job)只在主线程用
    传入的 db;每个节点在 worker 线程里用**各自的 SessionLocal**,互不干扰。
    """
    graph = workflow.graph
    order = topo_order(graph)  # 校验 DAG + 稳定顺序
    order_ids = [str(node["id"]) for node in order]
    nodes_by_id = {str(node["id"]): node for node in (graph.get("nodes") or [])}
    edges = list(graph.get("edges") or [])
    node_types = {nid: str(node.get("type")) for nid, node in nodes_by_id.items()}
    incoming: dict[str, list[dict[str, Any]]] = {nid: [] for nid in nodes_by_id}
    for edge in edges:
        source, target = str(edge.get("source")), str(edge.get("target"))
        if source in nodes_by_id and target in nodes_by_id:
            incoming[target].append(edge)
    total = max(len(order_ids), 1)
    wf_id, wf_name = workflow.id, workflow.name

    context: dict[str, dict[str, Any]] = {}
    executed: set[str] = set()
    done: set[str] = set()  # executed ∪ skipped
    lock = threading.Lock()

    def node_label(nid: str) -> str:
        return str(nodes_by_id[nid].get("name") or NODE_TYPES[node_types[nid]]["label"])

    def incoming_active(nid: str) -> bool:
        node_edges = incoming.get(nid, [])
        if not node_edges:
            return False
        for edge in node_edges:
            source = str(edge.get("source"))
            with lock:
                if source not in executed:
                    continue
                source_result = context.get(source, {}).get("result")
            if node_types.get(source) == "condition":
                wanted = str(edge.get("source_handle") or "true")
                if wanted != ("true" if source_result else "false"):
                    continue
            return True
        return False

    def run_node(nid: str) -> dict[str, Any]:
        node = nodes_by_id[nid]
        ntype = node_types[nid]
        with lock:
            snapshot = dict(context)
        config = apply_data_edges(nid, dict(node.get("config") or {}), edges, snapshot)
        config = interpolate_node_config(ntype, config, snapshot)
        if ntype == "start":
            merged = dict(config.get("params") or {})
            merged.update(params or {})
            return merged
        handler = get_executor(ntype)
        if handler is None:
            raise WorkflowDomainError(f"节点类型 {ntype} 没有执行器")
        # 每个节点用独立 session(SQLAlchemy Session 非线程安全),workflow 也在本 session 重取。
        with SessionLocal() as node_db:
            wf = node_db.get(Workflow, wf_id)
            return handler(node_db, wf, config)

    job.status = "running"
    job.message = f"工作流运行中: {wf_name}"
    db.commit()

    processed = 0
    scheduled: set[str] = set()
    error: Exception | None = None
    cancelled = False

    with ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_NODES, total)) as pool:
        futures: dict[Any, str] = {}

        def schedule_ready() -> None:
            nonlocal processed
            for nid in order_ids:
                if nid in scheduled:
                    continue
                if not all(str(edge.get("source")) in done for edge in incoming.get(nid, [])):
                    continue
                scheduled.add(nid)
                # By TYPE, not by the literal id "start". A start node named anything else has
                # no incoming edges, so it failed this check and was skipped — and with it
                # everything downstream, while the run still reported success with an empty
                # context. run_node already dispatches on type, so the two halves disagreed.
                if node_types.get(nid) != "start" and not incoming_active(nid):
                    with lock:
                        done.add(nid)
                    db.add(TaskEvent(job_id=job.id, type="workflow.node.skipped", payload={"node_id": nid, "name": node_label(nid)}))
                    processed += 1
                    job.progress = processed / total
                    db.commit()
                    continue
                db.add(
                    TaskEvent(
                        job_id=job.id,
                        type="workflow.node.started",
                        payload={"node_id": nid, "node_type": node_types[nid], "name": node_label(nid)},
                    )
                )
                db.commit()
                futures[pool.submit(run_node, nid)] = nid

        schedule_ready()
        while futures and error is None and not cancelled:
            # 用户取消(cancel_job 把 job 翻 failed):不再调度新节点,在飞的节点跑完即止。
            db.refresh(job)
            if job.status == "failed":
                cancelled = True
                db.add(TaskEvent(job_id=job.id, type="workflow.cancelled", payload={"pending": len(futures)}))
                db.commit()
                break
            completed, _ = wait(list(futures.keys()), timeout=0.5, return_when=FIRST_COMPLETED)
            for future in completed:
                nid = futures.pop(future)
                try:
                    outputs = future.result()
                except Exception as exc:  # noqa: BLE001 —— 任一节点失败即整流失败
                    error = exc
                    break
                with lock:
                    context[nid] = outputs
                    executed.add(nid)
                    done.add(nid)
                processed += 1
                db.add(
                    TaskEvent(
                        job_id=job.id,
                        type="workflow.node.finished",
                        payload={"node_id": nid, "name": node_label(nid), "outputs": _trim_outputs(outputs)},
                    )
                )
                job.progress = processed / total
                db.commit()
            if error is None and not cancelled:
                schedule_ready()

    if error is not None:
        raise error
    if cancelled:
        return context

    job.status = "succeeded"
    job.progress = 1.0
    job.message = f"工作流完成: {wf_name}"
    job.result = {"context": {nid: _trim_outputs(out) for nid, out in context.items()}}
    db.add(TaskEvent(job_id=job.id, type="workflow.finished", payload={"nodes": len(order_ids), "executed": len(executed)}))
    db.commit()
    return context


def _trim_outputs(outputs: dict[str, Any]) -> dict[str, Any]:
    """事件/结果里只存可读摘要,长文本截断,复杂对象计数。"""
    trimmed: dict[str, Any] = {}
    for key, value in outputs.items():
        if isinstance(value, str):
            trimmed[key] = value if len(value) <= 2000 else value[:2000] + "…"
        elif isinstance(value, list):
            trimmed[key] = f"[{len(value)} items]"
        elif isinstance(value, (int, float, bool)) or value is None:
            trimmed[key] = value
        else:
            trimmed[key] = str(value)[:500]
    return trimmed
