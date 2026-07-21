from __future__ import annotations

from pathlib import Path

import pytest
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
    assert any(model["provider"] == "openai-compatible" and model["adapter_available"] for model in models)

    res = client.post(
        "/api/generation/jobs",
        json={
            "workspace_id": ws["id"],
            "provider": "alibaba",
            "model": "qwen-image",
            "kind": "image",
            "prompt": "A clean professional video editor interface",
            "negative_prompt": "blurry",
            "parameters": {"size": "1024x1024"},
        },
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["job"]["kind"] == "ai_generation"
    assert payload["job"]["status"] == "queued"
    assert payload["generation"]["job_id"] == payload["job"]["id"]
    assert payload["generation"]["request"]["prompt"].startswith("A clean")
    assert payload["generation"]["request"]["negative_prompt"] == "blurry"
    assert payload["generation"]["session_id"] is not None


def test_generation_sessions_scope_jobs_and_can_be_managed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.api.routes.generation.start_generation_thread", lambda _generation_id: None)
    client = fresh_client()

    ws = client.post("/api/workspaces", json={"name": "Workspace"}).json()
    session = client.post("/api/generation/sessions", json={"workspace_id": ws["id"], "title": "海边女孩"}).json()
    res = client.post(
        "/api/generation/jobs",
        json={
            "workspace_id": ws["id"],
            "session_id": session["id"],
            "provider": "alibaba",
            "model": "qwen-image",
            "kind": "image",
            "prompt": "海边女孩",
            "parameters": {"size": "320x180"},
        },
    )

    assert res.status_code == 200
    generation = res.json()["generation"]
    assert generation["session_id"] == session["id"]
    scoped = client.get(f"/api/generation/jobs?workspace_id={ws['id']}&session_id={session['id']}").json()
    assert [item["id"] for item in scoped] == [generation["id"]]

    profile = client.post(
        "/api/settings/providers",
        json={
            "name": "OpenAI compatible",
            "vendor": "openai-compatible",
            "config": {
                "api_key": "sk-test",
                "base_url": "https://example.test/v1",
                "default_model": "gpt-image-2",
            },
        },
    ).json()
    renamed = client.patch(f"/api/generation/sessions/{session['id']}", json={"title": "女孩分镜"}).json()
    assert renamed["title"] == "女孩分镜"
    configured = client.patch(
        f"/api/generation/sessions/{session['id']}",
        json={"provider_profile_id": profile["id"], "model": "gpt-image-2", "kind": "image"},
    ).json()
    assert configured["provider_profile_id"] == profile["id"]
    assert configured["model"] == "gpt-image-2"
    assert client.delete(f"/api/generation/sessions/{session['id']}").status_code == 204
    assert client.get(f"/api/generation/jobs?workspace_id={ws['id']}&session_id={session['id']}").status_code == 404


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
