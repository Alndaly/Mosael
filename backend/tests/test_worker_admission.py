"""A queued worker must not hold a database connection while it waits, and must never vanish.

Two faults, verified to different depths — worth stating plainly.

The first is demonstrated below: every worker's first statement was `db.get(Job, job_id)`
OUTSIDE its try, so anything raising there killed the thread with the job left `queued`, no
error, and nothing to reconcile it (reconcile only runs at startup).

The second is the ordering. The transcode semaphore was taken INSIDE the session, after an
uncommitted read had already checked a connection out, so queued workers slept on the semaphore
holding one. I measured that directly — 14 of the pool's 15 connections held while waiting —
but I could NOT get a synthetic run to push it all the way to a checkout timeout, even with 40
barrier-synchronised threads and the timeout cut to 1s. So treat "60 videos lose 45 jobs" as a
plausible consequence rather than something reproduced here. The reordering stands on its own:
waiting on an unrelated semaphore while holding a scarce pooled connection is wrong whether or
not this particular machine crosses the timeout.
"""

from __future__ import annotations

import threading
import time

from app.core.db import SessionLocal, engine
from app.db.models import Job
from app.domain.jobs import run_job_guarded
from tests.util import fresh_client


def _job(workspace_id: str) -> str:
    with SessionLocal() as db:
        job = Job(workspace_id=workspace_id, kind="proxy", status="queued")
        db.add(job)
        db.commit()
        return job.id


def _workspace() -> str:
    client = fresh_client()
    return client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_a_worker_that_dies_in_its_prologue_marks_the_job_failed() -> None:
    """The exact shape of the original bug: the very first DB call raises."""
    ws = _workspace()
    job_id = _job(ws)

    def body() -> None:
        raise TimeoutError("QueuePool limit of size 5 overflow 10 reached")

    run_job_guarded(job_id, body, what="代理生成")

    with SessionLocal() as db:
        job = db.get(Job, job_id)
    assert job.status == "failed", "the job was left queued with no error, as before"
    assert "QueuePool" in job.error


def test_the_guard_does_not_touch_a_job_the_body_already_settled() -> None:
    ws = _workspace()
    job_id = _job(ws)

    def body() -> None:
        with SessionLocal() as db:
            job = db.get(Job, job_id)
            job.status = "succeeded"
            job.message = "done"
            db.commit()
        raise RuntimeError("noise after the fact")

    run_job_guarded(job_id, body, what="代理生成")

    with SessionLocal() as db:
        job = db.get(Job, job_id)
    assert job.status == "succeeded" and job.message == "done"


def test_many_queued_workers_do_not_exhaust_the_connection_pool(monkeypatch) -> None:
    """Far more workers than the pool has connections, all contending at once.

    This asserts the invariant — no job lost, no connection leaked — rather than claiming to
    reproduce the old failure, which I could not do synthetically (see the module docstring).
    It does hold the line against a regression that leaks connections or drops jobs.
    """
    ws = _workspace()
    job_ids = [_job(ws) for _ in range(40)]
    slots = threading.Semaphore(2)
    monkeypatch.setattr(engine.pool, "_timeout", 0.5, raising=False)

    def worker(job_id: str) -> None:
        with slots:  # BEFORE the session, as the real workers now do
            def body() -> None:
                with SessionLocal() as db:
                    job = db.get(Job, job_id)
                    job.status = "running"
                    db.commit()
                time.sleep(0.1)  # long enough that the queue outlasts the shortened timeout
                with SessionLocal() as db:
                    job = db.get(Job, job_id)
                    job.status = "succeeded"
                    db.commit()

            run_job_guarded(job_id, body, what="代理生成")

    threads = [threading.Thread(target=worker, args=(jid,)) for jid in job_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    with SessionLocal() as db:
        statuses = [db.get(Job, jid).status for jid in job_ids]

    assert statuses.count("succeeded") == 40, f"jobs were lost: {sorted(set(statuses))}"
    assert "queued" not in statuses, "a worker died leaving its job queued"
    assert engine.pool.checkedout() == 0, "a worker leaked a connection"
