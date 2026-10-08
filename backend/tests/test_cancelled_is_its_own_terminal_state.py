"""「已取消」是任务自己的终态,不是一种失败(ADR 0049)。

此前取消记成 `failed` + `error_key = jobErr_cancelled`:认得那个 key 的七八处各自翻译一遍,没认的(任务中心、统计、定时任务的
运行记录、工作流等子任务、智能体的回执)就把用户自己按的「停止」当成失败。现在:

- 取消落 `cancelled`,`error` 清空;谁取消的、从哪个任务级联下来的记在 `job.cancelled` 事件里;后代也是 `cancelled`。
- `cancelled` 进去就出不来,改成别的终态也不行;`failed → succeeded`(发布器)照旧可以。
- 租约过期照旧是 `failed`,它的后代被停下(`cancelled`)。外部执行器回报不了 `cancelled`。
- 智能体的回执说「已取消」;统计、管理页不把它算进失败,单列。
- 工作流等着的子任务被人单独停了:节点失败,说「子任务已被取消」。
- 棘轮:后端里不再写死 `("succeeded", "failed")` 当终态表,用 `jobs.TERMINAL_STATUSES`。
"""

from __future__ import annotations

import ast
import pathlib
import threading
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.unit_of_work import unit_of_work
from app.db.models import Job, TaskEvent, Workflow, now
from app.domain import dashboard
from app.domain import jobs as jobs_bus
from app.domain.agent import receipts
from app.domain.jobs import (
    JobError,
    JobStateError,
    cancel_job,
    claim_next_job,
    create_job,
    finish_job,
    report_job,
)
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows import executors as registry
from app.domain.workflows.engine import execute_graph
from app.domain.workflows.executors import common as executors_common
from tests.util import fresh_client, until, user_id


def _workspace() -> str:
    return fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]


def _running(db, workspace: str, *, kind: str = "render", parent: str | None = None) -> Job:
    job = create_job(db, created_by=None, workspace_id=workspace, kind=kind, payload={"subject": "成片"},
                     parent_job_id=parent)
    job.status = "running"
    db.flush()
    return job


def test_取消落cancelled_原因清空_谁取消的和从哪级联下来的记在事件里() -> None:
    workspace = _workspace()
    me = user_id()
    with unit_of_work() as db:
        parent = _running(db, workspace, kind="workflow")
        child = _running(db, workspace, parent=parent.id)
        parent_id, child_id = parent.id, child.id
    with unit_of_work() as db:
        cancel_job(db, db.get(Job, parent_id), by=me)

    with SessionLocal() as db:
        for job_id in (parent_id, child_id):
            job = db.get(Job, job_id)
            assert (job.status, job.error, job.error_key, job.message_key) == ("cancelled", None, "", "jobMsg_cancelled")
        said = {event.job_id: event.payload for event in db.scalars(select(TaskEvent).where(TaskEvent.type == "job.cancelled"))}
    assert said[parent_id] == {"by": me, "cascaded_from": None}
    assert said[child_id] == {"by": me, "cascaded_from": parent_id}, "级联下来的也是被停下的,记着从哪个任务来"


def test_cancelled进去就出不来_失败改成功照旧可以() -> None:
    workspace = _workspace()
    with unit_of_work() as db:
        stopped, failed = _running(db, workspace), _running(db, workspace)
        stopped_id, failed_id = stopped.id, failed.id
    with unit_of_work() as db:
        cancel_job(db, db.get(Job, stopped_id), by=None)
        finish_job(db, db.get(Job, failed_id), status="failed", error="发布器没回话")

    with SessionLocal() as db:
        job = db.get(Job, stopped_id)
        assert finish_job(db, job, status="succeeded") is False
        for later in ("succeeded", "failed", "running"):
            with pytest.raises(JobStateError):
                job.status = later
        db.rollback()
        late_success = db.get(Job, failed_id)
        late_success.status = "succeeded"  # 发布器被回收成失败之后又回报了成功:照实记成功
        db.commit()
        assert db.get(Job, failed_id).status == "succeeded"


def test_租约过期照旧是失败_它的后代被停下(monkeypatch) -> None:
    monkeypatch.setattr(jobs_bus, "_EXECUTION_MODES", {**jobs_bus._EXECUTION_MODES, "demo": "external"})
    workspace = _workspace()
    with unit_of_work() as db:
        create_job(db, created_by=None, workspace_id=workspace, kind="demo", payload={})
    with unit_of_work() as db:
        claimed = claim_next_job(db, worker="gone")
        child = _running(db, workspace, parent=claimed.id)
        claimed.lease_expires_at = now() - timedelta(seconds=1)
        claimed_id, child_id = claimed.id, child.id
    with unit_of_work() as db:
        assert jobs_bus.expire_worker_leases(db) == 1
    with SessionLocal() as db:
        assert (db.get(Job, claimed_id).status, db.get(Job, claimed_id).error_key) == ("failed", "jobErr_leaseExpired")
        assert db.get(Job, child_id).status == "cancelled"


def test_外部执行器回报不了cancelled_取消只由Mosael发起(monkeypatch) -> None:
    monkeypatch.setattr(jobs_bus, "_EXECUTION_MODES", {**jobs_bus._EXECUTION_MODES, "demo": "external"})
    workspace = _workspace()
    with unit_of_work() as db:
        create_job(db, created_by=None, workspace_id=workspace, kind="demo", payload={})
    with SessionLocal() as db:
        job = claim_next_job(db, worker="w")
        with pytest.raises(JobError) as refused:
            report_job(db, job, lease_token=job.lease_token, status="cancelled")
        assert refused.value.key == "jobErr_badReportStatus"


def test_智能体的回执说已取消_不说失败了() -> None:
    job = Job(status="cancelled", payload={"subject": "成片"}, error=None, message="已取消")
    assert receipts._summarize(job) == "「成片」已取消。"


def test_统计和管理页不把被停下的算进失败_单列() -> None:
    workspace = _workspace()
    with unit_of_work() as db:
        for status in ("succeeded", "failed", "failed"):
            job = _running(db, workspace)
            finish_job(db, job, status=status)
        stopped = _running(db, workspace)
        stopped_id = stopped.id
    with unit_of_work() as db:
        cancel_job(db, db.get(Job, stopped_id), by=None)

    with SessionLocal() as db:
        summary = dashboard.workspace_summary(db, workspace)
        overview = dashboard.deployment_overview(db)
    assert (summary["jobs_succeeded"], summary["jobs_failed"], summary["jobs_cancelled"]) == (1, 2, 1)
    today = summary["daily"][-1]
    assert (today["failed"], today["cancelled"]) == (2, 1)
    [day] = [one for one in overview["jobs_by_day"] if one["total"]]
    assert (day["total"], day["failed"], day["cancelled"]) == (4, 2, 1)


def test_工作流等着的子任务被单独停了_节点失败_说子任务已被取消(monkeypatch) -> None:
    """整轮停下时整轮是 cancelled(test_workflows.test_cancel_running_workflow);这里这一轮没在停,只有子任务被人在任务中心
    单独停了 —— 节点失败,此前说的是「子任务失败:已取消」。"""
    workspace = _workspace()
    me = user_id()
    with unit_of_work() as db:
        workflow = Workflow(workspace_id=workspace, name="等子任务", graph={"nodes": [], "edges": []})
        db.add(workflow)
        db.flush()
        workflow_id = workflow.id
    children: list[str] = []

    def waits_for_a_child(db, scope, config):
        child = create_job(db, created_by=None, workspace_id=scope.workspace_id, kind="render", payload={})
        db.commit()
        children.append(child.id)
        executors_common.wait_for_job(child.id, release=db)
        return {}

    monkeypatch.setitem(registry._REGISTRY, "note_create", waits_for_a_child)
    monkeypatch.setattr(executors_common, "CHILD_POLL_SECONDS", 0.05)
    graph = {
        "nodes": [{"id": "start", "type": "start", "config": {}},
                  {"id": "wait", "type": "note_create", "config": {"title": "t", "markdown": "m"}}],
        "edges": [{"source": "start", "target": "wait"}],
    }
    outcome: dict[str, BaseException] = {}

    def run() -> None:
        try:
            execute_graph(graph, wf_id=workflow_id, params={})
        except BaseException as exc:  # noqa: BLE001 — 断言里看是哪一种
            outcome["error"] = exc

    runner = threading.Thread(target=run)
    runner.start()
    try:
        assert until(lambda: bool(children)), "节点一直没起子任务"
        with unit_of_work() as db:
            cancel_job(db, db.get(Job, children[0]), by=me)
    finally:
        runner.join(30)
    assert not runner.is_alive(), "子任务被停下之后,等它的节点一直在等"
    error = outcome.get("error")
    assert isinstance(error, WorkflowDomainError) and error.key == "wfErr_childCancelled", repr(error)


def test_后端里不写死成功失败两个当终态表() -> None:
    """终态多了一个 cancelled:写死 ("succeeded", "failed") 的地方会把被停下的任务当成「还没结束」或者漏数。
    要终态就用 jobs.TERMINAL_STATUSES(它自己的定义除外)。"""
    app = pathlib.Path(__file__).resolve().parents[1] / "app"
    offenders = []
    for path in sorted(app.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
                values = [one.value for one in node.elts if isinstance(one, ast.Constant)]
                if len(values) == len(node.elts) == 2 and set(values) == {"succeeded", "failed"}:
                    offenders.append(f"{path.relative_to(app.parent)}:{node.lineno}")
    assert offenders == [], offenders
