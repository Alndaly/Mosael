"""任务在起它的那次事务**提交之后**才派发;事务回滚,任务连同它的线程都不存在。

此前 jobs.dispatch_job 先 `db.commit()` 再起线程:调用方事务里在它之前做的一切跟着落库,线程也跑起来了。
确认卡的执行体是「一个用例一个事务、炸了整个回滚」(approve_confirmation),对起任务的卡这句话就不成立 ——
执行体起了任务之后再炸,卡记「失败」,任务却已经落库、在跑(花钱的那种照样花)。
"""

from __future__ import annotations

import dataclasses

from app.core.db import SessionLocal
from app.db.models import Job
from app.domain.agent.confirmable import registry
from app.domain.agent.errors import ConfirmationError
from app.domain.jobs import wait_for_idle_jobs
from tests.util import fresh_client

GRAPH = {
    "nodes": [{"id": "start", "type": "start", "config": {"params": {}}},
              {"id": "t", "type": "template", "config": {"template": "x"}}],
    "edges": [{"id": "e", "source": "start", "target": "t"}],
}


def _workflow_jobs(ws: str) -> list[Job]:
    with SessionLocal() as db:
        return db.query(Job).filter(Job.kind == "workflow", Job.workspace_id == ws).all()


def _setup():
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    wf = client.post("/api/workflows", json={"workspace_id": ws, "name": "流", "graph": GRAPH}).json()["id"]
    return client, ws, wf


def test_执行体起了任务之后炸了_任务不落库也不跑(monkeypatch) -> None:
    client, ws, wf = _setup()
    spec = registry._TOOLS["run_workflow"]
    started: list[str] = []

    def starts_then_fails(db, confirmation, actor):
        #: 真的起任务(start_workflow_job → dispatch_job),然后执行体后半段炸了。
        started.append(spec.execute(db, confirmation, actor)["job_id"])
        raise ConfirmationError("起完任务之后,执行体后半段炸了")

    monkeypatch.setitem(registry._TOOLS, "run_workflow", dataclasses.replace(spec, execute=starts_then_fails))
    card = client.post("/api/confirmations", json={
        "workspace_id": ws, "tool": "run_workflow", "requested_by": "pi", "payload": {"workflow_id": wf, "params": {}},
    }).json()

    settled = client.post(f"/api/confirmations/{card['id']}/approve").json()
    wait_for_idle_jobs(timeout=10)

    assert settled["status"] == "failed"
    assert started, "执行体没走到起任务那一步,这条测试什么也没证明"
    assert _workflow_jobs(ws) == [], "卡记了失败,任务却已经落库、跑起来了"


def test_没炸的卡_任务在提交之后照常跑完() -> None:
    client, ws, wf = _setup()
    card = client.post("/api/confirmations", json={
        "workspace_id": ws, "tool": "run_workflow", "requested_by": "pi", "payload": {"workflow_id": wf, "params": {}},
    }).json()

    settled = client.post(f"/api/confirmations/{card['id']}/approve").json()
    wait_for_idle_jobs(timeout=10)

    assert settled["status"] == "executed", settled.get("error")
    [job] = _workflow_jobs(ws)
    assert job.id == settled["result"]["job_id"] and job.status == "succeeded", (job.status, job.error)


def test_界面上点运行_任务照常跑完() -> None:
    """路由就是入口:它提交了,任务才起来(此前这条路由不提交,全靠派发处替它提交)。"""
    client, ws, wf = _setup()
    run = client.post(f"/api/workflows/{wf}/run", json={"params": {}})
    assert run.status_code == 200, run.text
    wait_for_idle_jobs(timeout=10)
    with SessionLocal() as db:
        assert db.get(Job, run.json()["id"]).status == "succeeded"
