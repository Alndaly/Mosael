from __future__ import annotations

from fastapi.testclient import TestClient

from tests.util import fresh_client


def setup_clip(client: TestClient) -> tuple[dict, dict]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "project_id": project["id"], "kind": "video", "name": "S",
              "file_key": "media/s.mp4", "media_info": {"duration": 20}},
    ).json()
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"}
    ).json()
    track = next(t for t in sequence["tracks"] if t["kind"] == "video")
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": track["id"], "asset_id": asset["id"], "timeline_start": 1, "src_in": 0, "src_out": 10},
    ).json()
    return state, next(t for t in state["tracks"] if t["kind"] == "video")["clips"][0]


def video_clips(sequence: dict) -> list[dict]:
    return sorted(
        next(t for t in sequence["tracks"] if t["kind"] == "video")["clips"],
        key=lambda c: c["timeline_start"],
    )


def test_cut_multiple_ranges_in_one_operation() -> None:
    client = fresh_client()
    sequence, clip = setup_clip(client)
    # src [0,10) @1 minus [2,3) and [5,7) → kept [0,2)+[3,5)+[7,10) back-to-back from 1
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/cut-ranges",
        json={"ranges": [{"src_start": 5, "src_end": 7}, {"src_start": 2, "src_end": 3}]},
    ).json()
    pieces = video_clips(state)
    assert [(p["timeline_start"], p["src_in"], p["src_out"]) for p in pieces] == [
        (1, 0, 2), (3, 3, 5), (5, 7, 10),
    ]

    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    restored = video_clips(undone)
    assert len(restored) == 1 and restored[0]["id"] == clip["id"]

    redone = client.post(f"/api/sequences/{sequence['id']}/redo").json()
    assert len(video_clips(redone)) == 3


def test_overlapping_ranges_merge() -> None:
    client = fresh_client()
    sequence, clip = setup_clip(client)
    state = client.post(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/cut-ranges",
        json={"ranges": [{"src_start": 2, "src_end": 5}, {"src_start": 4, "src_end": 6}]},
    ).json()
    pieces = video_clips(state)
    assert [(p["src_in"], p["src_out"]) for p in pieces] == [(0, 2), (6, 10)]


def test_ranges_outside_clip_rejected() -> None:
    client = fresh_client()
    sequence, clip = setup_clip(client)
    res = client.post(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/cut-ranges",
        json={"ranges": [{"src_start": 15, "src_end": 18}]},
    )
    assert res.status_code == 422
