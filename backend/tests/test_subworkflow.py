"""Phase A:工作流即工具。父工作流用 call_workflow 调子工作流,传入参、拿子工作流「输出」节点
声明的具名输出;递归调用被拒;子 job 收纳到父下(parent_job_id)。"""

from __future__ import annotations

import time

from app.core.db import SessionLocal
from app.db.models import Job, Workflow
from app.domain.workflows import NODE_TYPES, create_workflow
from app.domain.workflows.engine import start_workflow_job
from app.domain.workflows.executors import registered_types
from tests.util import fresh_client


def _ws() -> str:
    client = fresh_client()
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def _run(wf_id: str, params: dict | None = None) -> tuple[str, dict, str | None, str]:
    with SessionLocal() as db:
        wf = db.get(Workflow, wf_id)
        job = start_workflow_job(db, wf, created_by=None, params=params or {})
        jid = job.id
    for _ in range(150):
        with SessionLocal() as db:
            j = db.get(Job, jid)
            if j.status in ("succeeded", "failed"):
                return j.status, j.result or {}, j.error, jid
        time.sleep(0.1)
    raise AssertionError("工作流没跑完")


def test_composition_nodes_registered() -> None:
    # 分组从「组合」并进了「流程」:节点面板上,子流程/调用/输出跟条件、循环是同一件事的不同
    # 形态 —— 都在决定"接下来往哪走",单开一组只是让人多扫一眼。
    for t in ("call_workflow", "output", "subgraph"):
        assert t in NODE_TYPES and t in registered_types()
        assert NODE_TYPES[t]["category"] == "流程"


def test_call_workflow_passes_inputs_and_returns_declared_output() -> None:
    ws = _ws()
    with SessionLocal() as db:
        child = create_workflow(
            db,
            workspace_id=ws,
            name="子流程",
            graph={
                "nodes": [
                    {"id": "start", "type": "start", "config": {}},
                    {"id": "out", "type": "output", "config": {"values": {"greeting": "你好 {{start.who}}"}}},
                ],
                "edges": [{"id": "e1", "source": "start", "target": "out"}],
            },
        )
        child_id = child.id
        # 父流程:start → 调用子流程 → 用自己的 output 节点把子输出转成父输出(完整 A 契约)
        parent = create_workflow(
            db,
            workspace_id=ws,
            name="父流程",
            graph={
                "nodes": [
                    {"id": "start", "type": "start", "config": {}},
                    {"id": "call", "type": "call_workflow", "config": {"workflow_id": child_id, "inputs": {"who": "世界"}}},
                    {"id": "out", "type": "output", "config": {"values": {"final": "{{call.output.greeting}}"}}},
                ],
                "edges": [
                    {"id": "e1", "source": "start", "target": "call"},
                    {"id": "e2", "source": "call", "target": "out"},
                ],
            },
        )
        parent_id = parent.id

    status, result, err, parent_job = _run(parent_id)
    assert status == "succeeded", err
    # 父流程的声明输出 = 子流程输出经父 output 节点转出(证明 call → output 契约全程通)
    assert result["output"] == {"final": "你好 世界"}

    # 子工作流 job 收纳到父下(parent_job_id 链)
    with SessionLocal() as db:
        child_jobs = db.query(Job).filter(Job.parent_job_id == parent_job, Job.kind == "workflow").all()
        assert len(child_jobs) == 1


def test_self_recursion_is_rejected() -> None:
    ws = _ws()
    with SessionLocal() as db:
        wf = create_workflow(
            db,
            workspace_id=ws,
            name="自调用",
            graph={
                "nodes": [
                    {"id": "start", "type": "start", "config": {}},
                    {"id": "call", "type": "call_workflow", "config": {"workflow_id": "SELF", "inputs": {}}},
                ],
                "edges": [{"id": "e1", "source": "start", "target": "call"}],
            },
        )
        wf_id = wf.id
        # 深拷贝重建,确保 SQLAlchemy 侦测到 JSON 变更(原地改同一 dict 不会触发)。
        import copy

        graph = copy.deepcopy(wf.graph)
        for node in graph["nodes"]:
            if node["id"] == "call":
                node["config"]["workflow_id"] = wf_id  # 指向自己
        wf.graph = graph
        db.commit()

    status, _result, err, _ = _run(wf_id)
    assert status == "failed"
    assert "递归" in (err or "")


def test_subgraph_seeds_input_and_resolves_output() -> None:
    """内嵌子图:inputs 在外层解析后播种 {{input.名}},output 模板对**子上下文**解析。"""
    ws = _ws()
    with SessionLocal() as db:
        wf = create_workflow(
            db,
            workspace_id=ws,
            name="子图·输入输出契约",
            graph={
                "nodes": [
                    {"id": "start", "type": "start", "config": {"params": {"seed": "世界"}}},
                    {
                        "id": "sg",
                        "type": "subgraph",
                        "config": {
                            "inputs": {"x": "{{start.seed}}"},  # 外层解析 → 播种 input.x
                            "body": {
                                "nodes": [
                                    {"id": "t1", "type": "template", "config": {"template": "你好 {{input.x}}"}},
                                ],
                                "edges": [],
                            },
                            "output": "{{t1.text}}",  # 对子上下文解析
                        },
                    },
                    {"id": "out", "type": "output", "config": {"values": {"final": "{{sg.output}}"}}},
                ],
                "edges": [
                    {"id": "e1", "source": "start", "target": "sg"},
                    {"id": "e2", "source": "sg", "target": "out"},
                ],
            },
        )
        wf_id = wf.id

    status, result, err, _ = _run(wf_id)
    assert status == "succeeded", err
    assert result["output"] == {"final": "你好 世界"}


def test_subgraph_nests_arbitrarily() -> None:
    """子图套子图:内层 subgraph 的 body/output 在跑外层 body 时也被保留原文(SUBGRAPH_TYPES),
    逐层解析——证明「可任意嵌套」。"""
    ws = _ws()
    with SessionLocal() as db:
        inner_body = {
            "nodes": [
                {"id": "leaf", "type": "template", "config": {"template": "深 {{input.y}}"}},
            ],
            "edges": [],
        }
        outer_body = {
            "nodes": [
                {
                    "id": "inner_sg",
                    "type": "subgraph",
                    "config": {"inputs": {"y": "{{input.x}}"}, "body": inner_body, "output": "{{leaf.text}}"},
                },
            ],
            "edges": [],
        }
        wf = create_workflow(
            db,
            workspace_id=ws,
            name="子图·嵌套",
            graph={
                "nodes": [
                    {"id": "start", "type": "start", "config": {"params": {"seed": "世界"}}},
                    {
                        "id": "outer_sg",
                        "type": "subgraph",
                        "config": {"inputs": {"x": "{{start.seed}}"}, "body": outer_body, "output": "{{inner_sg.output}}"},
                    },
                    {"id": "out", "type": "output", "config": {"values": {"final": "{{outer_sg.output}}"}}},
                ],
                "edges": [
                    {"id": "e1", "source": "start", "target": "outer_sg"},
                    {"id": "e2", "source": "outer_sg", "target": "out"},
                ],
            },
        )
        wf_id = wf.id

    status, result, err, _ = _run(wf_id)
    assert status == "succeeded", err
    assert result["output"] == {"final": "深 世界"}
