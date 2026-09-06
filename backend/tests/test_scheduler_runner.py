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
    from app.workers.scheduler import dispatch_job_for_task, _sync_run_states

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    def export(db, sequence_id, *, created_by):
        child = create_job(db, workspace_id=ws, kind="render", payload={}, created_by=created_by)
        db.commit()
        return child
    monkeypatch.setattr("app.domain.render.start_export", export)
    with SessionLocal() as db:
        task = ScheduledTask(workspace_id=ws, name="export", kind="render", trigger_type="manual", payload={})
        job = create_job(db, workspace_id=ws, kind="scheduled", payload={}, created_by=None)
        db.add(task)
        db.flush()
        run = ScheduledTaskRun(scheduled_task_id=task.id, job_id=job.id, status="queued")
        db.add(run)
        db.commit()
        dispatch_job_for_task(db, task, run, job)
        child = db.get(Job, job.result["export_job_id"])
        assert child.parent_job_id == job.id
        cancel_job(db, job)
        db.refresh(child)
        assert child.status == "failed"
        # A legacy worker's late result must not change the cancelled wrapper.
        child.status = "succeeded"
        db.commit()
        _sync_run_states(db)
        db.refresh(job)
        assert job.status == "failed" and job.error == "已取消"
        assert run.status == "failed"
