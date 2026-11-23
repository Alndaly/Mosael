"""执行体起步 / 收尾的那三句(`jobs.begin_job` / `jobs.complete_job`):生命周期只在这里测,各执行体只测「输入 → 产物」。"""

from __future__ import annotations

from sqlalchemy import select

from app.core.db import SessionLocal
from app.db.models import Job, TaskEvent
from app.domain.jobs import begin_job, complete_job, create_job, finish_job
from tests.util import fresh_client


def _job() -> str:
    workspace_id = fresh_client().post("/api/workspaces", json={"name": "W"}).json()["id"]
    with SessionLocal() as db:
        job = create_job(db, workspace_id=workspace_id, kind="trim", payload={}, created_by=None)
        db.commit()
        return job.id


def _events(db, job_id: str) -> list[str]:
    return list(db.scalars(select(TaskEvent.type).where(TaskEvent.job_id == job_id)))


def test_begin_then_complete_announces_both_and_carries_the_result() -> None:
    job_id = _job()
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert begin_job(db, job, "jobMsg_trimRunning", progress=0.1)
        db.commit()
        assert (job.status, job.progress, job.message_key) == ("running", 0.1, "jobMsg_trimRunning")
        assert complete_job(db, job, {"asset_id": "a1"}, "jobMsg_trimDone")
        db.commit()
        assert (job.status, job.progress, job.result, job.message_key) == ("succeeded", 1.0, {"asset_id": "a1"}, "jobMsg_trimDone")
        events = _events(db, job_id)
        assert events.count("job.running") == 1 and events.count("job.succeeded") == 1, events


def test_a_job_cancelled_while_queued_never_starts() -> None:
    job_id = _job()
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        finish_job(db, job, status="cancelled")
        db.commit()
        assert begin_job(db, job, "jobMsg_trimRunning") is False
        db.commit()
        assert job.status == "cancelled"
        assert "job.running" not in _events(db, job_id)


def test_a_job_cancelled_mid_run_is_not_reported_as_done() -> None:
    job_id = _job()
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert begin_job(db, job, "jobMsg_trimRunning")
        finish_job(db, job, status="cancelled")
        db.commit()
        assert complete_job(db, job, {"asset_id": "a1"}, "jobMsg_trimDone") is False
        db.commit()
        assert job.status == "cancelled"
        assert "job.succeeded" not in _events(db, job_id)
