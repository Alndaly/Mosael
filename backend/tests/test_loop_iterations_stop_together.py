"""循环被叫停时说「已取消」,并发遍历一项失败后其余在跑的项不再往下开节点。

## 现场

- 一项失败、或别的节点失败让这一轮停下时,循环里在跑的那一项抛的是 wfErr_cancelled,却被包成
  「第 1/1 次迭代失败:已取消」—— 读起来像这一项自己出了错。
- 并发遍历(`concurrency` > 1)一项失败后,停的信号只在 `_iterate_concurrently` 那一层,各项自己的图
  看不见:其余在跑的项照样一个节点一个节点往下跑,付费节点照开。
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Job, TaskEvent, Workflow
from app.domain.jobs import create_job
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows import engine as wf_engine
from app.domain.workflows.executors import get_executor
from tests.util import fresh_client


def _workflow_and_job() -> tuple[str, str]:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        workflow = Workflow(workspace_id=ws, name="流程", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.flush()
        job = create_job(db, workspace_id=ws, kind="workflow", payload={"workflow_id": workflow.id}, created_by=None)
        job.status = "running"
        db.commit()
        return workflow.id, job.id


def _fakes(monkeypatch, fakes: dict) -> None:
    """只替**图里另一个**节点(让它失败);被测的循环、体里的延时都走真的执行器。"""
    monkeypatch.setattr(wf_engine, "get_executor", lambda kind: fakes.get(kind) or get_executor(kind))


def test_循环被别的节点失败叫停时_报的是已取消_不是第几次迭代失败(monkeypatch) -> None:
    def boom(db, scope, config):
        time.sleep(0.3)
        raise WorkflowDomainError("隔壁失败了")

    _fakes(monkeypatch, {"x_boom": boom})
    workflow_id, job_id = _workflow_and_job()
    graph = {
        "nodes": [
            {"id": "start", "type": "start", "config": {}},
            {"id": "boom", "type": "x_boom", "name": "隔壁", "config": {}},
            {"id": "L", "type": "loop_foreach", "name": "循环", "config": {
                "items": ["a"],
                "body": {"nodes": [{"id": "wait", "type": "delay", "config": {"seconds": 30}}], "edges": []},
            }},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "boom"}, {"id": "e2", "source": "start", "target": "L"}],
    }
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        with pytest.raises(WorkflowDomainError, match="隔壁失败了"):
            wf_engine.execute_graph(graph, wf_id=workflow_id, job=job, db=db)
        db.commit()
        failed = [
            event.payload for event in db.scalars(select(TaskEvent).where(TaskEvent.job_id == job_id))
            if event.type == "workflow.node.failed" and event.payload.get("node_id") == "L"
        ]
    assert len(failed) == 1
    assert failed[0]["error_key"] == "wfErr_cancelled", failed[0]
    assert "迭代" not in failed[0]["error"]
