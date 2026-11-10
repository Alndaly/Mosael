"""一次工作流运行走到哪了:给智能体「盯进度」用的一份摘要。

`get_job` 只说得出整条运行的状态和一个进度数;一条整片要跑几个小时,里面分镜写好没有、第几镜在出图出视频、哪一步
失败了,它都看不见。这里从两处读:**顶层已经落定的节点**(`workflow_run_steps`,从中断处继续也靠它)和**这次运行派生
的全部子任务**(出图、出视频、配音……顺着 `parent_job_id` 收齐),合成一份看得懂的进度。花了多少钱同 `run_costs`。
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Job, WorkflowRevision, WorkflowRunStep
from app.domain.billing.usage import run_costs

#: 失败的子任务最多列几条(每条一句原因):多了模型读不过来,也都是同一个原因。
MAX_FAILURES = 5
#: 一句失败原因最多多长。
MAX_REASON = 300


def _descendants(db: Session, job_id: str) -> list[Job]:
    ids: set[str] = set()
    frontier = {job_id}
    found: list[Job] = []
    while frontier:
        rows = list(db.scalars(select(Job).where(Job.parent_job_id.in_(frontier))))
        frontier = {row.id for row in rows} - ids
        ids |= frontier
        found.extend(row for row in rows if row.id in frontier)
    return found


def _top_nodes(db: Session, job: Job) -> tuple[dict[str, str], set[str]]:
    """这次运行钉住的那一版图里:顶层节点 id → 名字(给人看的那个),以及开始节点的 id(它交的是开始参数,
    不留落定记录 —— 运行起来了它就算做完)。"""
    revision = db.get(WorkflowRevision, str((job.payload or {}).get("workflow_revision_id") or ""))
    names: dict[str, str] = {}
    starts: set[str] = set()
    for node in ((revision.graph if revision else None) or {}).get("nodes") or []:
        name = node.get("name")
        if isinstance(name, dict):
            name = name.get("zh") or next(iter(name.values()), "")
        node_id = str(node.get("id"))
        names[node_id] = str(name or node_id)
        if node.get("type") == "start":
            starts.add(node_id)
    return names, starts


def run_progress(db: Session, job: Job) -> dict[str, Any]:
    """`job` 是一次工作流运行(`kind == "workflow"`)。交回:状态、进度、顶层做完了哪几步 / 还剩哪几步、
    子任务按种类和状态的计数、最近几条失败原因、花费。运行成功后落定记录会被清掉,这时「做完的步骤」就是全部。"""
    names, starts = _top_nodes(db, job)
    done = [node_id for node_id in names if node_id in starts and job.status != "queued"] + [
        row.node_id for row in db.scalars(
            select(WorkflowRunStep).where(WorkflowRunStep.job_id == job.id, WorkflowRunStep.scope == "",
                                          WorkflowRunStep.outputs.is_not(None))
        )
    ]
    finished = job.status == "succeeded"
    remaining = [] if finished else [node_id for node_id in names if node_id not in set(done)]
    children = _descendants(db, job.id)
    counts = Counter(f"{child.kind}:{child.status}" for child in children)
    failures = [
        {"kind": child.kind, "reason": (child.error or child.message or "")[:MAX_REASON]}
        for child in sorted(children, key=lambda one: one.created_at, reverse=True)
        if child.status == "failed"
    ][:MAX_FAILURES]
    return {
        "job_id": job.id,
        "workflow_id": str((job.payload or {}).get("workflow_id") or ""),
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": (job.error or "")[:MAX_REASON],
        "steps_done": [names.get(node_id, node_id) for node_id in (list(names) if finished else done)],
        "steps_remaining": [names[node_id] for node_id in remaining],
        "subtasks": dict(sorted(counts.items())),
        "recent_failures": failures,
        "costs": run_costs(db, job.id),
        #: 中断、失败、取消的运行能从中断处接着跑(continue_workflow_run),做完的步骤不再做。
        "can_continue": job.status in ("failed", "cancelled"),
    }


__all__ = ["run_progress"]
