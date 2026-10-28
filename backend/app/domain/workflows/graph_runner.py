"""节点里「再跑一张图」的入口:循环体、内嵌子图(executors.common.run_body_to_the_end)、调用另一个工作流
(executors.subworkflow)都经这里回到执行内核。

**这是一道缝,实现由引擎在它自己的模块末尾登记**(见 engine 末尾的 `graph_runner.use`,和「接着跑等人确认的运行」
同一个手法)。递归的解释器天然是一个环:引擎按注册表找执行器,容器类执行器又要回头调引擎跑一张图。
此前执行器在函数里延迟 import 引擎来绕开它 —— 环还在,只是导入期看不见(见 tests/test_import_layering)。
现在执行器只认识这道缝,引擎认识执行器,方向是单向的。

没接上就调(只 import 了执行器、没 import 引擎的脚本)直接报错,不静默地什么都不跑。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

    from app.db.models import Job, Workflow
    from app.domain.workflows.graph_run import GraphRun

RunGraph = Callable[..., "GraphRun"]
StartWorkflowJob = Callable[..., "Job"]

_run_graph: RunGraph | None = None
_start_workflow_job: StartWorkflowJob | None = None


def use(*, run_graph: RunGraph, start_workflow_job: StartWorkflowJob) -> None:
    """引擎登记它自己的两个入口。"""
    global _run_graph, _start_workflow_job
    _run_graph, _start_workflow_job = run_graph, start_workflow_job


def run_graph(graph: dict[str, Any], *, wf_id: str, initial_context: dict[str, Any] | None = None,
              entry_is_root: bool = False) -> GraphRun:
    """在当前这轮运行里跑一张内嵌的图(见 engine.run_graph 的「子图」那一条)。"""
    if _run_graph is None:
        raise RuntimeError("workflow engine not registered: import app.domain.workflows.engine first")
    return _run_graph(graph, wf_id=wf_id, initial_context=initial_context, entry_is_root=entry_is_root)


def start_workflow_job(db: Session, workflow: Workflow, *, created_by: str | None,
                       params: dict[str, Any] | None = None) -> Job:
    """把另一个工作流起成当前任务的子任务(见 engine.start_workflow_job)。"""
    if _start_workflow_job is None:
        raise RuntimeError("workflow engine not registered: import app.domain.workflows.engine first")
    return _start_workflow_job(db, workflow, created_by=created_by, params=params)


__all__ = ["run_graph", "start_workflow_job", "use"]
