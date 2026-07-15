from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.db import Base, engine, init_db
from app.main import app
from tests.util import fresh_client


def reset_db(tmp_path: Path) -> None:
    Base.metadata.drop_all(bind=engine)
    init_db()


def test_generation_job_creates_job_and_generation_record(tmp_path: Path) -> None:
    client = fresh_client()

    ws = client.post("/api/workspaces", json={"name": "Workspace"}).json()
    models = client.get("/api/generation/models?kind=image").json()
    assert any(model["model"] == "qwen-image" for model in models)

    res = client.post(
        "/api/generation/jobs",
        json={
            "workspace_id": ws["id"],
            "provider": "alibaba",
            "model": "qwen-image",
            "kind": "image",
            "prompt": "A clean professional video editor interface",
            "parameters": {"size": "1024x1024"},
        },
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["job"]["kind"] == "ai_generation"
    assert payload["job"]["status"] == "queued"
    assert payload["generation"]["job_id"] == payload["job"]["id"]
    assert payload["generation"]["request"]["prompt"].startswith("A clean")


def test_scheduled_task_run_creates_job(tmp_path: Path) -> None:
    client = fresh_client()

    ws = client.post("/api/workspaces", json={"name": "Workspace"}).json()
    task = client.post(
        "/api/scheduled-tasks",
        json={
            "workspace_id": ws["id"],
            "name": "Nightly render",
            "kind": "render",
            "trigger_type": "interval",
            "schedule": {"seconds": 3600},
            "payload": {"sequence_id": "seq_1"},
        },
    ).json()

    assert task["next_run_at"] is not None

    res = client.post(f"/api/scheduled-tasks/{task['id']}/run")
    assert res.status_code == 200
    payload = res.json()
    assert payload["run"]["scheduled_task_id"] == task["id"]
    assert payload["job"]["kind"] == "render"
    assert payload["job"]["payload"]["scheduled_task_id"] == task["id"]
