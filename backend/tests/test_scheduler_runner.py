from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.core.db import SessionLocal
from app.db.models import Job, ScheduledTask, ScheduledTaskRun, now
from app.domain.scheduler.operations import SchedulerDomainError, compute_next_run_at
from app.workers.scheduler import tick
from tests.util import fresh_client


def test_daily_next_run_math() -> None:
    reference = datetime(2026, 7, 15, 8, 0)
    before = compute_next_run_at("daily", {"time": "09:30"}, reference)
    assert before == datetime(2026, 7, 15, 9, 30)
    after = compute_next_run_at("daily", {"time": "07:00"}, reference)
    assert after == datetime(2026, 7, 16, 7, 0)


def test_weekly_next_run_math() -> None:
    reference = datetime(2026, 7, 15, 8, 0)  # a Wednesday (weekday=2)
    friday = compute_next_run_at("weekly", {"weekday": 4, "time": "10:00"}, reference)
    assert friday == datetime(2026, 7, 17, 10, 0)
    past_today = compute_next_run_at("weekly", {"weekday": 2, "time": "07:00"}, reference)
    assert past_today == datetime(2026, 7, 22, 7, 0)
    with pytest.raises(SchedulerDomainError):
        compute_next_run_at("weekly", {"weekday": 9}, reference)


@pytest.fixture(autouse=True)
def _idle_executor(monkeypatch):
    """循环本身的测试不关心任务做什么:登记一个什么都不做的种类,包装任务就停在排队中。"""
    from app.domain.scheduler.executors import SCHEDULED_EXECUTORS

    monkeypatch.setitem(SCHEDULED_EXECUTORS, "media_check", lambda db, task, run, job: None)


def make_due_task(client, kind: str = "media_check", trigger_type: str = "interval") -> str:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    task = client.post(
        "/api/scheduled-tasks",
        json={
            "workspace_id": ws["id"],
            "name": "T",
            "kind": kind,
            "trigger_type": trigger_type,
            "schedule": {"seconds": 3600} if trigger_type == "interval" else {"run_at": "2020-01-01T00:00:00"},
        },
    ).json()
    # Force the task due now.
    with SessionLocal() as db:
        row = db.get(ScheduledTask, task["id"])
        row.next_run_at = now() - timedelta(seconds=5)
        db.commit()
    return task["id"]


def test_tick_claims_due_task_and_creates_run() -> None:
    client = fresh_client()
    task_id = make_due_task(client)
    with SessionLocal() as db:
        created = tick(db)
        assert len(created) == 1
        run = db.get(ScheduledTaskRun, created[0])
        assert run.scheduled_task_id == task_id
        assert run.job_id is not None
        task = db.get(ScheduledTask, task_id)
        assert task.next_run_at > now()  # advanced by an hour
        assert task.last_run_at is not None


def test_tick_does_not_reenter_active_task() -> None:
    client = fresh_client()
    task_id = make_due_task(client)
    with SessionLocal() as db:
        first = tick(db)
        assert len(first) == 1
        # Force due again while the first run is still active (kind has no executor → queued).
        task = db.get(ScheduledTask, task_id)
        task.next_run_at = now() - timedelta(seconds=1)
        db.commit()
        second = tick(db)
        assert second == []
        task = db.get(ScheduledTask, task_id)
        assert task.next_run_at > now()  # pushed forward instead of re-running


def test_once_task_disables_after_trigger() -> None:
    client = fresh_client()
    task_id = make_due_task(client, trigger_type="once")
    with SessionLocal() as db:
        created = tick(db)
        assert len(created) == 1
        task = db.get(ScheduledTask, task_id)
        assert task.enabled is False
        assert task.next_run_at is None


def test_run_state_syncs_from_job() -> None:
    client = fresh_client()
    make_due_task(client)
    with SessionLocal() as db:
        created = tick(db)
        run = db.get(ScheduledTaskRun, created[0])
        job = db.get(Job, run.job_id)
        job.status = "succeeded"
        db.commit()
        tick(db)
        run = db.get(ScheduledTaskRun, created[0])
        assert run.status == "succeeded"
        assert run.finished_at is not None


def test_scheduled_export_cancels_child_and_stays_cancelled(monkeypatch):
    from app.domain.jobs import create_job, cancel_job
    from app.domain.scheduler.executors import dispatch_scheduled_job, sync_run_states

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    def export(db, sequence_id, *, created_by):
        child = create_job(db, workspace_id=ws, kind="render", payload={}, created_by=created_by)
        db.commit()
        return child
    monkeypatch.setattr("app.domain.render.start_export", export)
    with SessionLocal() as db:
        task = ScheduledTask(workspace_id=ws, name="export", kind="render", trigger_type="manual", payload={})
        job = create_job(db, workspace_id=ws, kind="render", payload={}, created_by=None)
        db.add(task)
        db.flush()
        run = ScheduledTaskRun(scheduled_task_id=task.id, job_id=job.id, status="queued")
        db.add(run)
        db.commit()
        dispatch_scheduled_job(db, task, run, job)
        child = db.get(Job, job.result["delegated_job_id"])
        assert child.parent_job_id == job.id
        cancel_job(db, job)
        db.refresh(child)
        assert child.status == "failed"
        # A legacy worker's late result must not change the cancelled wrapper.
        child.status = "succeeded"
        db.commit()
        sync_run_states(db)
        db.refresh(job)
        assert job.status == "failed" and job.error == "已取消"
        assert run.status == "failed"


class Test三个触发入口是同一个:
    """调度循环、「立即运行」、webhook 都经 domain.scheduler.trigger_scheduled_task。此前各拼一套:
    「立即运行」不查重入,连点两下就是两次并发的同一个任务。"""

    def _workflow_task(self, client, trigger_type: str = "manual") -> tuple[str, str]:
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        workflow = client.post("/api/workflows", json={"workspace_id": ws, "name": "流", "graph": {
            "nodes": [{"id": "start", "type": "start", "config": {"params": {}}}], "edges": [],
        }}).json()
        task = client.post("/api/scheduled-tasks", json={
            "workspace_id": ws, "name": "任务", "kind": "workflow", "trigger_type": trigger_type,
            "schedule": {}, "payload": {"workflow_id": workflow["id"]},
        })
        assert task.status_code == 200, task.text
        return ws, task.json()["id"]

    def test_立即运行也不重入(self) -> None:
        client = fresh_client()
        _ws, task_id = self._workflow_task(client)
        with SessionLocal() as db:
            task = db.get(ScheduledTask, task_id)
            db.add(ScheduledTaskRun(scheduled_task_id=task.id, status="running"))
            db.commit()
        response = client.post(f"/api/scheduled-tasks/{task_id}/run")
        assert response.status_code == 409 and "还没跑完" in response.text

    def test_立即运行记下最近一次运行时间(self) -> None:
        client = fresh_client()
        _ws, task_id = self._workflow_task(client)
        assert client.post(f"/api/scheduled-tasks/{task_id}/run").status_code == 200
        with SessionLocal() as db:
            assert db.get(ScheduledTask, task_id).last_run_at is not None

    def test_认不出的种类建不出来(self) -> None:
        client = fresh_client()
        ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
        response = client.post("/api/scheduled-tasks", json={
            "workspace_id": ws, "name": "x", "kind": "scheduled", "trigger_type": "manual", "schedule": {}, "payload": {},
        })
        assert response.status_code == 422 and "定时任务只能是" in response.text

    def test_不跑别的工作区的工作流(self) -> None:
        client = fresh_client()
        _ws, task_id = self._workflow_task(client)
        other = client.post("/api/workspaces", json={"name": "别人的"}).json()["id"]
        foreign = client.post("/api/workflows", json={"workspace_id": other, "name": "别人的流", "graph": {
            "nodes": [{"id": "start", "type": "start", "config": {"params": {}}}], "edges": [],
        }}).json()["id"]
        with SessionLocal() as db:
            task = db.get(ScheduledTask, task_id)
            task.payload = {"workflow_id": foreign}
            db.commit()
        job = client.post(f"/api/scheduled-tasks/{task_id}/run").json()["job"]
        assert job["status"] == "failed" and "不存在" in job["error"]

    def test_只有领域在决定定时任务做什么(self) -> None:
        """棘轮:路由和轮询循环不再自己派发。"""
        import pathlib

        app = pathlib.Path(__file__).resolve().parents[1] / "app"
        for relative in ("api/routes/hooks.py", "api/routes/scheduler.py", "workers/scheduler.py"):
            text = (app / relative).read_text(encoding="utf-8")
            assert "dispatch_scheduled_job" not in text and "has_active_run" not in text, relative
