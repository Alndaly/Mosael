from __future__ import annotations

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


def test_generate_image_confirmation_carries_ai_cost_permission() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    data = client.post(
        "/api/confirmations",
        json={
            "workspace_id": ws["id"],
            "tool": "generate_image",
            "payload": {"prompt": "a lighthouse at dawn", "provider": "mock", "model": "mock-image",
                        "parameters": {"size": "320x180"}},
        },
    ).json()
    assert data["permission"] == "ai-cost"
    approved = client.post(f"/api/confirmations/{data['id']}/approve").json()
    assert approved["status"] == "executed", approved.get("error")
    assert approved["result"]["job_id"]


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
