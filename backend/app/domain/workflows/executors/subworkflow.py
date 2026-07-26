"""组合/嵌套:输出节点(工作流的输出契约)与「调用工作流」节点(工作流即工具)。

call_workflow 把另一个已保存的工作流当子流程,走**完整主引擎**跑(作为子 job,复用 jobs 的父子
收纳 + 级联取消),拿它「输出」节点声明的结果。防递归(沿父 job 链判环)+ 防过深。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Job, Workflow
from app.domain.jobs import current_parent_job_id
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import register
from app.domain.workflows.executors.common import wait_for_job

MAX_NEST_DEPTH = 8


@register("output")
def output(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    """声明工作流输出:config['values'] 里的引用已被引擎插值,原样作为具名输出返回。"""
    values = config.get("values")
    return {"output": dict(values) if isinstance(values, dict) else {}}


def _guard_recursion(db: Session, target_id: str, current_wf_id: str) -> None:
    """沿父 job 链收集祖先工作流 id;目标若已在链上 → 递归;链太深 → 过深。用父子链判环,
    规避跨线程 contextvar 传不过去的问题(子工作流在独立线程里跑)。"""
    chain: set[str] = {current_wf_id}
    job_id = current_parent_job_id()
    depth = 0
    while job_id and depth < MAX_NEST_DEPTH + 2:
        job = db.get(Job, job_id)
        if job is None:
            break
        wf_id = (job.payload or {}).get("workflow_id")
        if wf_id:
            chain.add(str(wf_id))
        job_id = job.parent_job_id
        depth += 1
    if target_id in chain:
        raise WorkflowDomainError("工作流递归调用(直接或间接调用了自身),已阻止")
    if depth >= MAX_NEST_DEPTH:
        raise WorkflowDomainError(f"工作流嵌套过深(超过 {MAX_NEST_DEPTH} 层),已阻止")


@register("call_workflow")
def call_workflow(db: Session, workflow: Workflow, config: dict[str, Any]) -> dict[str, Any]:
    from app.domain.workflows.engine import start_workflow_job

    target_id = str(config.get("workflow_id") or "").strip()
    if not target_id:
        raise WorkflowDomainError("请选择要调用的工作流")
    target = db.get(Workflow, target_id)
    if target is None or target.workspace_id != workflow.workspace_id:
        raise WorkflowDomainError("被调用的工作流不存在")

    _guard_recursion(db, target_id, workflow.id)

    inputs = config.get("inputs")
    params = dict(inputs) if isinstance(inputs, dict) else {}
    # start_workflow_job 建的子 job 经 create_job 读 contextvar,parent = 当前工作流 job → 自动收纳。
    child = start_workflow_job(db, target, params=params)
    final = wait_for_job(child.id)
    result = final.result or {}
    # 优先给「输出」节点声明的具名输出;没有则退回整份上下文(向后兼容)。
    return {"output": result.get("output") or result.get("context") or {}}
