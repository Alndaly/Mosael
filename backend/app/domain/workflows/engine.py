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
from app.db.models import Job, Workflow, WorkflowRevision
from app.domain.jobs import create_job, dispatch_job, emit_job_event, reset_parent_job, set_parent_job, say
from app.domain.notifications import notify
from app.domain.workflows import (
    NODE_TYPES,
    WorkflowDomainError,
    topo_order,
    validate_graph,
)
from app.domain.workflows.binding import apply_data_edges, interpolate_node_config
from app.domain.workflows.executors import get_executor
from app.domain.workflows.revisions import WorkflowRevisionError, current_workflow_revision

logger = logging.getLogger(__name__)

MAX_PARALLEL_NODES = 8


def start_workflow_job(
    db: Session, workflow: Workflow, *, created_by: str | None, params: dict[str, Any] | None = None, job: Job | None = None
) -> Job:
    """创建(或复用)workflow job，并把它固定到启动瞬间的不可变修订。"""
    from app.domain.plugins.nodes import plugin_node_types

    try:
        revision = current_workflow_revision(db, workflow)
    except WorkflowRevisionError as exc:
        raise WorkflowDomainError(str(exc)) from exc
    errors = validate_graph(revision.graph, extra_types=plugin_node_types(db))
    if errors:
        raise WorkflowDomainError("；".join(errors))
    pinned_payload = {
        "workflow_id": workflow.id,
        "workflow_revision_id": revision.id,
        "workflow_revision": revision.revision,
        "workflow_graph_hash": revision.graph_hash,
        "params": params or {},
        "subject": workflow.name,
    }
    if job is None:
        job = create_job(
            db,
            workspace_id=workflow.workspace_id,
            kind="workflow",
            created_by=created_by,
            payload=pinned_payload,
            message="jobMsg_workflowQueued", message_params={"name": workflow.name},
        )
    else:
        # 调度器/子工作流可复用外部创建的 job；同样必须把修订钉进审计载荷。
        job.payload = {**(job.payload or {}), **pinned_payload}
    # 经总线派发,不自己起线程。此前这里是一句裸的 threading.Thread —— 于是工作流成了唯一
    # 绕开 dispatch_job 的 job kind,代价有两个:一是它的执行模式形同虚设(把 workflow 注册成
    # external 也照样在进程内跑),二是线程没有 JOB_THREAD_NAME,`wait_for_idle_jobs()` 按名字
    # 找不到它 —— 测试里 fresh_client() 就会在一个还活着的工作流线程底下 drop_all,炸成
    # 「no such table: task_events」,而且记在当时恰好在跑的那条**无关**用例头上。
    # (那正是 jobs.py 里 JOB_THREAD_NAME 的注释所断言的不变量:派发点只有一处。)
    dispatch_job(db, job, lambda: _run_workflow_thread(workflow.id, revision.id, job.id, params or {}))
    return job


def _run_workflow_thread(workflow_id: str, revision_id: str, job_id: str, params: dict[str, Any]) -> None:
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        workflow = db.get(Workflow, workflow_id)
        revision = db.get(WorkflowRevision, revision_id)
        if job is None or workflow is None:
            return
        try:
            if revision is None or revision.workflow_id != workflow.id:
                raise WorkflowDomainError("工作流执行绑定的修订快照不存在")
            logger.info("workflow job %s: running '%s'", job_id, workflow.name)
            run_workflow(db, workflow, revision, job, params)
            db.refresh(job)
            logger.info("workflow job %s: '%s' finished (%s)", job_id, workflow.name, job.status)
        except Exception as exc:  # noqa: BLE001 — 线程内兜底,失败必须落到 job 上
            logger.exception("workflow job %s ('%s') crashed", job_id, workflow.name)
            failure = _failure_payload(exc)
            job.status = "failed"
            job.error = failure["error"]
            # JobOut 也保留一份终态现场。事件流是完整时间线；result.failure 让只读取 job 的
            # 消费方同样能展示诊断，而不是只能看到一句“失败”。
            job.result = {**(job.result or {}), "failure": failure}
            say(job, "jobMsg_workflowFailed")
            emit_job_event(db, job.id, "workflow.failed", failure)
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


def _failure_payload(exc: Exception) -> dict[str, Any]:
    """把异常变成任务总线可持久化的失败现场。"""
    payload: dict[str, Any] = {"error": str(exc)[:500]}
    details = getattr(exc, "details", None)
    if isinstance(details, dict) and details:
        payload["details"] = details
    return payload


def execute_graph(
    graph: dict[str, Any],
    *,
    wf_id: str,
    initial_context: dict[str, Any] | None = None,
    params: dict[str, Any] | None = None,
    job: Job | None = None,
    db: Session | None = None,
    entry_is_root: bool = False,
) -> tuple[dict[str, Any], bool]:
    """依赖驱动的并行执行内核(顶层工作流与循环体/子图共用):前驱全完成才可运行,彼此独立的
    分支**同时**跑(线程池)。条件分支按 source_handle 匹配才算活跃;未被活跃入边触达的节点整段
    跳过(Dify 语义)。返回 (最终上下文, 是否被取消)。

    - 顶层:传 job + db,发事件/进度、支持取消;只有 start 类型是入口。
    - 子图(循环体等):不传 job;`entry_is_root=True` 让无入边节点也作为入口;用 initial_context
      播种(如 {loop:{item,index}})。子图节点不重设 parent job(沿用外层节点已设的父上下文)。
    """
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
    wf_job_id = job.id if job is not None else None
    has_job = job is not None and db is not None

    context: dict[str, Any] = dict(initial_context or {})
    executed: set[str] = set()
    done: set[str] = set()  # executed ∪ skipped
    lock = threading.Lock()

    def node_label(nid: str) -> str:
        return str(nodes_by_id[nid].get("name") or NODE_TYPES[node_types[nid]]["label"])

    def event(kind: str, payload: dict[str, Any]) -> None:
        if has_job:
            emit_job_event(db, job.id, kind, payload)
            db.commit()

    def is_entry(nid: str) -> bool:
        # start 类型永远是入口;子图里无入边的根也是入口。
        if node_types.get(nid) == "start":
            return True
        return entry_is_root and not incoming.get(nid)

    def incoming_active(nid: str) -> bool:
        node_edges = incoming.get(nid, [])
        if not node_edges:
            return False
        for edge in node_edges:
            source = str(edge.get("source"))
            with lock:
                if source not in executed:
                    continue
                source_result = context.get(source, {}).get("result") if isinstance(context.get(source), dict) else None
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
        # 顶层:本节点派生的子任务归到这条工作流 job 下(任务中心收纳)。子图不重设——沿用外层
        # 节点已设的父上下文(见 jobs.create_job / set_parent_job)。
        token = set_parent_job(wf_job_id) if has_job else None
        try:
            with SessionLocal() as node_db:  # 每节点独立 session(非线程安全),workflow 本 session 重取
                wf = node_db.get(Workflow, wf_id)
                return handler(node_db, wf, config)
        finally:
            if token is not None:
                reset_parent_job(token)

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
                if not is_entry(nid) and not incoming_active(nid):
                    with lock:
                        done.add(nid)
                    event("workflow.node.skipped", {"node_id": nid, "name": node_label(nid)})
                    processed += 1
                    if has_job:
                        job.progress = processed / total
                        db.commit()
                    continue
                event("workflow.node.started", {"node_id": nid, "node_type": node_types[nid], "name": node_label(nid)})
                futures[pool.submit(run_node, nid)] = nid

        schedule_ready()
        while futures and error is None and not cancelled:
            if has_job:
                # 用户取消(cancel_job 把 job 翻 failed):不再调度新节点,在飞的节点跑完即止。
                db.refresh(job)
                if job.status == "failed":
                    cancelled = True
                    event("workflow.cancelled", {"pending": len(futures)})
                    # 在飞的节点必须补一条终态事件再走。否则它们只有 started 没有收尾,
                    # 前端(WorkflowRunHistory.toSteps 按 started/finished 配对)会把它们永远
                    # 停在 running —— 转圈不停、耗时按「现在 − 开始」一直往上走(线上见过 95590s)。
                    for pending_nid in futures.values():
                        event(
                            "workflow.node.failed",
                            {"node_id": pending_nid, "name": node_label(pending_nid), "error": "已取消"},
                        )
                    break
            completed, _ = wait(list(futures.keys()), timeout=0.5, return_when=FIRST_COMPLETED)
            for future in completed:
                nid = futures.pop(future)
                try:
                    outputs = future.result()
                except Exception as exc:  # noqa: BLE001 —— 任一节点失败即整流失败
                    error = exc
                    event(
                        "workflow.node.failed",
                        {"node_id": nid, "name": node_label(nid), **_failure_payload(exc)},
                    )
                    break
                with lock:
                    context[nid] = outputs
                    executed.add(nid)
                    done.add(nid)
                processed += 1
                event("workflow.node.finished", {"node_id": nid, "name": node_label(nid), "outputs": _trim_outputs(outputs)})
                if has_job:
                    job.progress = processed / total
                    db.commit()
            if error is None and not cancelled:
                schedule_ready()

    if error is not None:
        raise error
    return context, cancelled


def run_workflow(
    db: Session,
    workflow: Workflow,
    revision: WorkflowRevision,
    job: Job,
    params: dict[str, Any],
) -> dict[str, Any]:
    """执行固定修订；编辑当前工作流不会改变已排队任务的图。"""
    graph = revision.graph
    node_types = {str(node["id"]): str(node.get("type")) for node in (graph.get("nodes") or [])}
    job.status = "running"
    say(job, "jobMsg_workflowRunning", name=workflow.name)
    db.commit()

    context, cancelled = execute_graph(graph, wf_id=workflow.id, params=params, job=job, db=db)
    if cancelled:
        return context

    # 「输出」节点声明的具名输出:被 call_workflow 调用时,调用方拿的就是这个契约(见 executors/subworkflow)。
    output_values: dict[str, Any] = {}
    for nid, out in context.items():
        if node_types.get(nid) == "output" and isinstance(out, dict):
            output_values.update(out.get("output") or {})

    job.status = "succeeded"
    job.progress = 1.0
    say(job, "jobMsg_workflowDone", name=workflow.name)
    job.result = {
        "workflow_revision_id": revision.id,
        "workflow_revision": revision.revision,
        "workflow_graph_hash": revision.graph_hash,
        "context": {nid: _trim_outputs(out) for nid, out in context.items()},
        "output": output_values,
    }
    emit_job_event(
        db,
        job.id,
        "workflow.finished",
        {"nodes": len(node_types), "executed": len(context), "workflow_revision": revision.revision},
    )
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
