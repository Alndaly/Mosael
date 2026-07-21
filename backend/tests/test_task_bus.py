from __future__ import annotations

from datetime import timedelta

from app.core.db import SessionLocal
from app.db.models import Job, TaskEvent, now
from app.domain.jobs import clear_finished_jobs, prune_task_events, reconcile_orphaned_jobs
from tests.util import fresh_client


def seed_job(db, workspace_id: str, *, status: str, events: int, age_days: int = 0) -> Job:
    job = Job(workspace_id=workspace_id, kind="render", status=status, message="x")
    db.add(job)
    db.flush()
    for index in range(events):
        db.add(TaskEvent(job_id=job.id, type=f"e{index}", payload={}))
    if age_days:
        job.updated_at = now() - timedelta(days=age_days)
    db.commit()
    return job


def event_count(db, job_id: str) -> int:
    return len(db.query(TaskEvent).filter(TaskEvent.job_id == job_id).all())


def test_retention_rules() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        active = seed_job(db, ws["id"], status="running", events=10)
        recent_done = seed_job(db, ws["id"], status="succeeded", events=10)
        old_done = seed_job(db, ws["id"], status="failed", events=10, age_days=40)

        removed = prune_task_events(db)
        assert removed == 15  # 5 trimmed from recent_done + 10 wiped from old_done
        assert event_count(db, active.id) == 10       # active keeps everything
        assert event_count(db, recent_done.id) == 5   # terminal keeps last N
        assert event_count(db, old_done.id) == 0      # 30-day window wipes detail
        assert db.get(Job, old_done.id) is not None   # the job summary row stays


def test_job_events_endpoint_and_clear_finished() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        done = seed_job(db, ws["id"], status="succeeded", events=3)
        running = seed_job(db, ws["id"], status="running", events=1)
        done_id, running_id = done.id, running.id

    events = client.get(f"/api/jobs/{done_id}/events").json()
    assert [event["type"] for event in events] == ["e0", "e1", "e2"]

    result = client.delete(f"/api/jobs/finished?workspace_id={ws['id']}").json()
    assert result == {"removed": 1}
    remaining = client.get(f"/api/jobs?workspace_id={ws['id']}").json()
    assert [job["id"] for job in remaining] == [running_id]


def test_reconcile_orphaned_jobs_on_restart() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    with SessionLocal() as db:
        running = seed_job(db, ws["id"], status="running", events=1)
        queued = Job(workspace_id=ws["id"], kind="transcribe", status="queued", message="x")
        # Publish jobs run on the external desktop worker — a backend restart must NOT fail them.
        publish = Job(workspace_id=ws["id"], kind="publish", status="running", message="x")
        done = seed_job(db, ws["id"], status="succeeded", events=1)
        db.add_all([queued, publish])
        db.commit()
        ids = (running.id, queued.id, publish.id, done.id)

    with SessionLocal() as db:
        assert reconcile_orphaned_jobs(db) == 2  # running + queued in-process jobs

    with SessionLocal() as db:
        states = {jid: db.get(Job, jid).status for jid in ids}
    running_id, queued_id, publish_id, done_id = ids
    assert states[running_id] == "failed"
    assert states[queued_id] == "failed"
    assert states[publish_id] == "running"    # external worker untouched
    assert states[done_id] == "succeeded"     # already terminal, left alone
