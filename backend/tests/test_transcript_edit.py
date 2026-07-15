from __future__ import annotations

from fastapi.testclient import TestClient

from tests.util import fresh_client


def setup_clip(client: TestClient) -> tuple[dict, dict]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    asset = client.post(
        "/api/assets",
        json={
            "workspace_id": ws["id"],
            "project_id": project["id"],
            "kind": "video",
            "name": "Talk",
            "file_key": "media/talk.mp4",
            "media_info": {"duration": 10},
        },
    ).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"},
    ).json()
    track = next(t for t in sequence["tracks"] if t["kind"] == "video")
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": track["id"], "asset_id": asset["id"], "timeline_start": 2, "src_in": 1, "src_out": 9},
    ).json()
    return state, clips(state)[0]


def clips(sequence: dict) -> list[dict]:
    return next(t for t in sequence["tracks"] if t["kind"] == "video")["clips"]


def test_cut_middle_splits_and_ripples() -> None:
    client = fresh_client()
    sequence, clip = setup_clip(client)
    # clip: timeline [2,10), src [1,9). Cut src [4,6) → left src [1,4) at t=2, right src [6,9) at t=5
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/cut-range",
        json={"src_start": 4, "src_end": 6},
    ).json()
    result = sorted(clips(state), key=lambda c: c["timeline_start"])
    assert len(result) == 2
    left, right = result
    assert (left["timeline_start"], left["src_in"], left["src_out"]) == (2, 1, 4)
    assert (right["timeline_start"], right["src_in"], right["src_out"]) == (5, 6, 9)


def test_cut_at_head_trims_only() -> None:
    client = fresh_client()
    sequence, clip = setup_clip(client)
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/cut-range",
        json={"src_start": 0, "src_end": 3},
    ).json()
    result = clips(state)
    assert len(result) == 1
    assert (result[0]["timeline_start"], result[0]["src_in"], result[0]["src_out"]) == (2, 3, 9)


def test_cut_everything_deletes_clip() -> None:
    client = fresh_client()
    sequence, clip = setup_clip(client)
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/cut-range",
        json={"src_start": 0, "src_end": 99},
    ).json()
    assert clips(state) == []


def test_cut_outside_range_rejected() -> None:
    client = fresh_client()
    sequence, clip = setup_clip(client)
    res = client.post(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/cut-range",
        json={"src_start": 9.5, "src_end": 10},
    )
    assert res.status_code == 422


def test_cut_is_undoable_and_redoable() -> None:
    client = fresh_client()
    sequence, clip = setup_clip(client)
    cut = client.post(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/cut-range",
        json={"src_start": 4, "src_end": 6},
    ).json()
    assert len(clips(cut)) == 2

    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    restored = clips(undone)
    assert len(restored) == 1
    assert restored[0]["id"] == clip["id"]
    assert (restored[0]["src_in"], restored[0]["src_out"]) == (1, 9)

    redone = client.post(f"/api/sequences/{sequence['id']}/redo").json()
    assert len(clips(redone)) == 2
