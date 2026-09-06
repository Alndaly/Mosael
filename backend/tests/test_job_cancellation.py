"""Cancelling a job has to stop the work and stay cancelled.

Cancel only flipped a database row. ffmpeg (and the ASR/TTS workers) ran to completion, burning
the CPU the user asked to stop, and then the worker — holding a Job loaded before the
cancellation — assigned status="succeeded" over the top. The cancelled export reappeared in the
library as a succeeded job, with 「已取消」 still sitting in its error field.
"""

from __future__ import annotations

import subprocess
import sys

from app.core.child_process import ChildProcess
from app.core.db import SessionLocal
from app.db.models import Job
from app.domain.jobs import (
    TERMINAL_STATUSES,
    cancel_job,
    finish_job,
    kill_job_child,
    register_job_child,
    unregister_job_child,
)
from tests.util import fresh_client


def _job(workspace_id: str, status: str = "running") -> str:
    with SessionLocal() as db:
        job = Job(workspace_id=workspace_id, kind="render", status=status)
        db.add(job)
        db.commit()
        return job.id


def _workspace() -> tuple[object, str]:
    client = fresh_client()
    return client, client.post("/api/workspaces", json={"name": "W"}).json()["id"]


def test_a_worker_cannot_overwrite_a_cancellation() -> None:
    _, ws = _workspace()
    job_id = _job(ws)

    with SessionLocal() as db:
        worker_view = db.get(Job, job_id)  # what the worker loaded when it started

        with SessionLocal() as other:
            cancel_job(other, other.get(Job, job_id))

        # The worker now finishes and tries to report success against its stale object.
        wrote = finish_job(db, worker_view, status="succeeded", message="Export complete")
        db.commit()

    assert wrote is False, "finish_job let the worker clobber the cancellation"
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status == "failed" and job.error == "已取消"
        assert job.message == "已取消", "the cancellation's own message was relabelled"


def test_finish_job_writes_normally_when_nothing_cancelled() -> None:
    _, ws = _workspace()
    job_id = _job(ws)
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert finish_job(db, job, status="succeeded", progress=1.0) is True
        db.commit()
    with SessionLocal() as db:
        assert db.get(Job, job_id).status == "succeeded"


def test_cancelling_kills_the_registered_child() -> None:
    _, ws = _workspace()
    job_id = _job(ws)
    process = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(120)"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    child = ChildProcess(process)
    register_job_child(job_id, child)
    try:
        with SessionLocal() as db:
            cancel_job(db, db.get(Job, job_id))
        # If cancel had only flipped the row, this would block until the sleep finished.
        assert process.wait(timeout=10) != 0, "the child outlived its cancelled job"
    finally:
        unregister_job_child(job_id)
        child.kill()


def test_killing_an_unregistered_job_is_a_no_op() -> None:
    assert kill_job_child("no-such-job") is False


def test_a_finished_job_stops_being_cancellable() -> None:
    _, ws = _workspace()
    job_id = _job(ws, status="succeeded")
    with SessionLocal() as db:
        job = db.get(Job, job_id)
        assert job.status in TERMINAL_STATUSES
        try:
            cancel_job(db, job)
        except ValueError:
            return
    raise AssertionError("cancelling an already-finished job should be refused")


def test_cancelled_queued_export_never_starts_renderer(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.domain import render

    _, ws = _workspace()
    job_id = _job(ws, status="queued")
    with SessionLocal() as db:
        cancel_job(db, db.get(Job, job_id))
    renderer = Mock(side_effect=RuntimeError("renderer must not start"))
    monkeypatch.setattr(render, "execute_render", renderer)
    render._run_export(job_id, SimpleNamespace(render_plan_hash="test"))
    renderer.assert_not_called()
    with SessionLocal() as db:
        assert db.get(Job, job_id).error == "已取消"


def test_child_registered_after_cancellation_is_killed():
    from unittest.mock import Mock

    _, ws = _workspace()
    job_id = _job(ws)
    with SessionLocal() as db:
        cancel_job(db, db.get(Job, job_id))
    child = Mock()
    try:
        register_job_child(job_id, child)
        child.kill.assert_called_once()
    finally:
        unregister_job_child(job_id)


def test_generation_cancelled_during_provider_call_does_not_import_results(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from app.db.models import GenerationJob
    from app.domain.generation import runner

    _, ws = _workspace()
    job_id = _job(ws, status="queued")
    with SessionLocal() as db:
        generation = GenerationJob(workspace_id=ws, job_id=job_id, kind="image", provider="test", model="test", request={})
        db.add(generation)
        db.commit()
        generation_id = generation.id
    def generate(*args):
        with SessionLocal() as other:
            cancel_job(other, other.get(Job, job_id))
        return SimpleNamespace(output_paths=[tmp_path / "not-imported.png"])
    adapter = SimpleNamespace(requires_credentials=lambda: False, validate_request=lambda r: None,
                              supports_progress_callbacks=False, generate=generate)
    monkeypatch.setattr(runner, "get_generation_adapter", lambda *a: adapter)
    monkeypatch.setattr("app.domain.providers.resolve_connection", lambda *a, **kw: None)
    monkeypatch.setattr(runner, "_record_generation_usage", lambda *a, **kw: None)
    importer = Mock(side_effect=AssertionError("cancelled output must not be imported"))
    monkeypatch.setattr(runner, "register_file_asset", importer)
    runner._run_generation(generation_id)
    importer.assert_not_called()
    with SessionLocal() as db:
        assert db.get(Job, job_id).error == "已取消"
