"""条件节点的 `result` 是一个**输出**,接它的数据边只说"值从哪来",不说"走哪条分支"。

条件节点在画布上有两种出口:右侧的 真 / 假 两个分支接点(控制边,带 source_handle),和
`out:result` 输出接点(数据边)。引擎此前对来自条件节点的**每一条**边都做分支路由,数据边没有
source_handle,于是被当成「真」分支 —— 把 `result` 接进一个模板,条件为假时那个模板**整个被跳过**,
而用户想要的恰恰是"把真假写进去"。在模板里写 `{{判断.result}}` 也一样:保存时它被规范化成
同一条数据边。

路由语义属于**控制边**。哪些节点会分支、分支叫什么,由节点声明(NODE_TYPES 的 `branches`),
引擎路由、保存校验、规范化折叠边都读这一格:

- 规范化会把"同一对节点间已有数据边"的无 handle 控制边折叠掉 —— 但从会分支的节点出发的
  控制边带着路由语义(没写 handle 就是「真」),折叠掉它等于把"只在真时跑"改成"总是跑"。
"""

from __future__ import annotations

import time

import pytest

from app.core.db import SessionLocal
from app.db.models import Job, Workflow
from app.domain.workflows import BRANCHING_NODE_TYPES, NODE_TYPES, create_workflow
from app.domain.workflows.engine import start_workflow_job
from tests.util import user_id, fresh_client


def _run(graph: dict) -> tuple[dict, dict]:
    ws = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = create_workflow(db, workspace_id=ws, name="条件", graph=graph, created_by=user_id())
        saved = workflow.graph
        job_id = start_workflow_job(db, db.get(Workflow, workflow.id), created_by=None).id
    for _ in range(100):
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            if job.status in ("succeeded", "failed"):
                assert job.status == "succeeded", job.error
                return job.result["context"], saved
        time.sleep(0.05)
    raise AssertionError("工作流没跑完")


def _condition(right: str) -> dict:
    return {"id": "check", "type": "condition", "config": {"left": "a", "op": "equals", "right": right}}


@pytest.mark.parametrize(("right", "expected"), [("a", "结果:true"), ("b", "结果:false")])
def test_接了_result_的节点两个分支都跑(right: str, expected: str) -> None:
    context, _ = _run(
        {
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                _condition(right),
                {"id": "say", "type": "template", "config": {"template": ""}, "inputs": ["template"]},
                {"id": "wrap", "type": "template", "config": {"template": "结果:{{say.text}}"}},
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "check"},
                # 画布上从 out:result 拖到 in:template 画出来的就是这一条。
                {"id": "d1", "source": "check", "target": "say", "kind": "data",
                 "source_output": "result", "target_input": "template"},
                {"id": "e2", "source": "say", "target": "wrap"},
            ],
        }
    )
    assert context["wrap"] == {"text": expected}


@pytest.mark.parametrize(("right", "runs"), [("a", True), ("b", False)])
def test_没写_handle_的分支边保存后仍然只在真时跑(right: str, runs: bool) -> None:
    """控制边没写 handle 就是「真」分支;同一对节点间再有一条数据边(`{{check.result}}` 规范化出来的)
    时,规范化此前把这条控制边当成多余的折叠掉 —— 路由语义跟着没了。"""
    context, saved = _run(
        {
            "nodes": [
                {"id": "start", "type": "start", "config": {}},
                _condition(right),
                {"id": "say", "type": "template", "config": {"template": "{{check.result}}"}},
            ],
            "edges": [
                {"id": "e1", "source": "start", "target": "check"},
                {"id": "e2", "source": "check", "target": "say"},
            ],
        }
    )
    assert any(edge["id"] == "e2" for edge in saved["edges"]), "带路由语义的控制边被规范化折叠掉了"
    assert ("say" in context) is runs


def test_会分支的节点由声明决定() -> None:
    assert BRANCHING_NODE_TYPES == {"condition"}
    assert NODE_TYPES["condition"]["branches"] == ["true", "false"]
