from __future__ import annotations

import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from tests.util import fresh_client


def setup_sequence(client: TestClient) -> tuple[dict, dict, dict, dict]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "project_id": project["id"], "kind": "video", "name": "Src",
              "file_key": "media/src.mp4", "media_info": {"duration": 10}},
    ).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"},
    ).json()
    return ws, project, asset, sequence


def video_clips(sequence: dict) -> list[dict]:
    return next(t for t in sequence["tracks"] if t["kind"] == "video")["clips"]


def wait_job(client: TestClient, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.time() + timeout
    job = client.get(f"/api/jobs/{job_id}").json()
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.05)
    return job


def test_edit_timeline_requires_approval_then_executes() -> None:
    client = fresh_client()
    ws, _, asset, sequence = setup_sequence(client)
    track = next(t for t in sequence["tracks"] if t["kind"] == "video")

    confirmation = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "edit_timeline",
            "requested_by": "pi",
            "payload": {
                "sequence_id": sequence["id"],
                "operations": [
                    {"kind": "insert_clip", "track_id": track["id"], "asset_id": asset["id"],
                     "timeline_start": 0, "src_in": 0, "src_out": 5},
                    {"kind": "add_track", "track_kind": "video"},
                ],
            },
        },
    )
    assert confirmation.status_code == 200, confirmation.text
    data = confirmation.json()
    assert data["status"] == "pending"
    assert data["permission"] == "edit"
    assert "2 个时间线操作" in data["summary"]

    # Nothing applied while pending.
    state = client.get(f"/api/sequences/{sequence['id']}").json()
    assert video_clips(state) == []

    approved = client.post(f"/api/confirmations/{data['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    assert approved["result"]["applied_operations"] == 2

    state = client.get(f"/api/sequences/{sequence['id']}").json()
    assert len(video_clips(state)) == 1
    assert "V2" in [t["name"] for t in state["tracks"]]
    # AI edits stay undoable (plan §10.2).
    assert state["can_undo"] is True


def test_edit_workflow_applies_granular_ops() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "WF"}).json()
    assert [n["type"] for n in workflow["graph"]["nodes"]] == ["start"]

    confirmation = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "edit_workflow",
            "requested_by": "pi",
            "payload": {
                "workflow_id": workflow["id"],
                "operations": [
                    {"kind": "add_node", "type": "llm", "node_id": "llm_1", "config": {"prompt": "hi {{start.q}}"}},
                    {"kind": "connect", "source": "start", "target": "llm_1"},
                ],
            },
        },
    )
    assert confirmation.status_code == 200, confirmation.text
    data = confirmation.json()
    assert data["status"] == "pending"
    assert "2 个工作流编辑" in data["summary"]

    # Nothing applied while pending.
    current = client.get(f"/api/workflows/{workflow['id']}").json()
    assert [n["type"] for n in current["graph"]["nodes"]] == ["start"]

    approved = client.post(f"/api/confirmations/{data['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")

    after = client.get(f"/api/workflows/{workflow['id']}").json()
    types = sorted(n["type"] for n in after["graph"]["nodes"])
    assert types == ["llm", "start"]
    assert any(e["source"] == "start" and e["target"] == "llm_1" for e in after["graph"]["edges"])


def test_edit_workflow_rejects_bad_ops() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "WF"}).json()
    # Connecting to a node that doesn't exist must fail fast at request time.
    bad = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "edit_workflow",
            "requested_by": "pi",
            "payload": {"workflow_id": workflow["id"], "operations": [{"kind": "connect", "source": "start", "target": "ghost"}]},
        },
    )
    assert bad.status_code == 422, bad.text
    assert "ghost" in bad.text or "不存在" in bad.text


def test_edit_workflow_clear_can_delete_start_and_create_confirmation() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "WF"}).json()
    add = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "edit_workflow",
            "requested_by": "pi",
            "payload": {
                "workflow_id": workflow["id"],
                "operations": [
                    {"kind": "add_node", "type": "llm", "node_id": "llm_1", "config": {"prompt": "hi"}},
                    {"kind": "connect", "source": "start", "target": "llm_1"},
                ],
            },
        },
    ).json()
    client.post(f"/api/confirmations/{add['id']}/approve")

    clear = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "edit_workflow",
            "requested_by": "pi",
            "payload": {
                "workflow_id": workflow["id"],
                "operations": [
                    {"kind": "remove_node", "node_id": "start"},
                    {"kind": "remove_node", "node_id": "llm_1"},
                ],
            },
        },
    )

    assert clear.status_code == 200, clear.text
    data = clear.json()
    assert data["status"] == "pending"
    assert data["payload"]["operations"] == [
        {"kind": "remove_node", "node_id": "start"},
        {"kind": "remove_node", "node_id": "llm_1"},
    ]
    assert "2 个工作流编辑" in data["summary"]

    approved = client.post(f"/api/confirmations/{data['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    after = client.get(f"/api/workflows/{workflow['id']}").json()
    assert after["graph"]["nodes"] == []
    assert after["graph"]["edges"] == []


def test_edit_workflow_can_delete_only_start() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    workflow = client.post("/api/workflows", json={"workspace_id": ws["id"], "name": "WF"}).json()

    res = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "edit_workflow",
            "requested_by": "pi",
            "payload": {
                "workflow_id": workflow["id"],
                "operations": [{"kind": "remove_node", "node_id": "start"}],
            },
        },
    )

    assert res.status_code == 200, res.text
    data = res.json()
    assert data["status"] == "pending"
    approved = client.post(f"/api/confirmations/{data['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    after = client.get(f"/api/workflows/{workflow['id']}").json()
    assert after["graph"]["nodes"] == []


def test_reject_leaves_timeline_untouched() -> None:
    client = fresh_client()
    ws, _, asset, sequence = setup_sequence(client)
    track = next(t for t in sequence["tracks"] if t["kind"] == "video")
    data = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "edit_timeline",
            "payload": {
                "sequence_id": sequence["id"],
                "operations": [{"kind": "insert_clip", "track_id": track["id"], "asset_id": asset["id"],
                                "timeline_start": 0, "src_in": 0, "src_out": 5}],
            },
        },
    ).json()
    rejected = client.post(f"/api/confirmations/{data['id']}/reject").json()
    assert rejected["status"] == "rejected"
    state = client.get(f"/api/sequences/{sequence['id']}").json()
    assert video_clips(state) == []
    # A resolved confirmation cannot be approved afterwards.
    assert client.post(f"/api/confirmations/{data['id']}/approve").status_code == 409


def test_generate_image_confirmation_carries_ai_cost_permission(monkeypatch) -> None:
    monkeypatch.setattr("app.domain.generation.runner.start_generation_thread", lambda _generation_id: None)
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    data = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "generate_image",
            "payload": {"prompt": "a lighthouse at dawn", "provider": "alibaba", "model": "qwen-image",
                        "parameters": {"size": "320x180"}},
        },
    ).json()
    assert data["permission"] == "ai-cost"
    approved = client.post(f"/api/confirmations/{data['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    assert approved["result"]["job_id"]
    job = client.get(f"/api/jobs/{approved['result']['job_id']}").json()
    assert job["status"] == "queued"


def test_generate_audio_confirmation_uses_tts_default(monkeypatch) -> None:
    captured: dict = {}

    def fake_start_synthesis(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(id="tts-job-1")

    monkeypatch.setattr("app.audio.voices.start_synthesis", lambda _db, **kwargs: fake_start_synthesis(**kwargs))
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    profile = client.post(
        "/api/settings/providers",
        json={"name": "Speech", "vendor": "openai-tts", "config": {"api_key": "sk-tts", "default_model": "tts-model"}},
    ).json()
    client.put(
        "/api/settings/provider-defaults/tts",
        json={"provider_profile_id": profile["id"], "model": "tts-model"},
    )
    data = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "generate_audio",
            "payload": {"text": "旁白测试", "voice": "nova"},
        },
    ).json()
    assert data["permission"] == "ai-cost"
    approved = client.post(f"/api/confirmations/{data['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    assert approved["result"]["job_id"] == "tts-job-1"
    assert captured["engine"] == "openai-tts"
    assert captured["provider_profile_id"] == profile["id"]
    assert captured["engine_model"] == "tts-model"
    assert captured["engine_voice"] == "nova"


def test_invalid_payloads_rejected() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    unknown = client.post(
        "/api/confirmations", json={"workspace_id": ws["id"], "tool": "drop_database", "payload": {}}
    )
    assert unknown.status_code == 422
    bad_seq = client.post(
        "/api/confirmations",
        json={"workspace_id": ws["id"], "tool": "render_sequence", "payload": {"sequence_id": "nope"}},
    )
    assert bad_seq.status_code == 422
    empty_ops = client.post(
        "/api/confirmations",
        json={"workspace_id": ws["id"], "tool": "edit_timeline", "payload": {"sequence_id": "nope", "operations": []}},
    )
    assert empty_ops.status_code == 422
