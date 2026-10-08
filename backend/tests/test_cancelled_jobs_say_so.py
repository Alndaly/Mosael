"""A job somebody stopped says so in the job API instead of passing for a failure.

Cancelling used to write ``status="failed"`` with the ``jobErr_cancelled`` key, and every place that only read
``status`` — the task center first of all — turned the user's own "stop" into a red "… · failed". Cancelled is now
its own terminal status (ADR 0049): no error, and a real failure stays a failure.
"""

from __future__ import annotations

from app.core.db import SessionLocal
from app.db.models import Job
from app.domain.jobs import finish_job
from tests.util import fresh_client


def _job(workspace_id: str, status: str = "running") -> str:
    with SessionLocal() as db:
        job = Job(workspace_id=workspace_id, kind="render", status=status)
        db.add(job)
        db.commit()
        return job.id


def test_a_stopped_job_is_reported_as_cancelled() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    job_id = _job(ws)

    stopped = client.post(f"/api/jobs/{job_id}/cancel")
    assert stopped.status_code == 200, stopped.text
    assert (stopped.json()["status"], stopped.json()["error"]) == ("cancelled", None)
    listed = {row["id"]: row for row in client.get("/api/jobs", params={"workspace_id": ws}).json()}
    assert listed[job_id]["status"] == "cancelled"


def test_a_real_failure_and_a_success_are_not_cancelled() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()["id"]
    failed_id, done_id = _job(ws), _job(ws)
    with SessionLocal() as db:
        finish_job(db, db.get(Job, failed_id), status="failed", error="ffmpeg exited 1")
        finish_job(db, db.get(Job, done_id), status="succeeded", progress=1.0)
        db.commit()

    listed = {row["id"]: row for row in client.get("/api/jobs", params={"workspace_id": ws}).json()}
    assert (listed[failed_id]["status"], listed[failed_id]["error"]) == ("failed", "ffmpeg exited 1")
    assert listed[done_id]["status"] == "succeeded"
