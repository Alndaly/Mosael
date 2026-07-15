from __future__ import annotations

from fastapi.testclient import TestClient

from tests.util import fresh_client


def setup_three_clips(client: TestClient) -> tuple[dict, list[dict]]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    asset = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "project_id": project["id"], "kind": "video", "name": "S",
              "file_key": "media/s.mp4", "media_info": {"duration": 30}},
    ).json()
    sequence = client.post(
        "/api/sequences", json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"}
    ).json()
    track = next(t for t in sequence["tracks"] if t["kind"] == "video")
    state = sequence
    # A @0 len 4, B @5 len 3, C @10 len 2
    for start, src_out in ((0, 4), (5, 3), (10, 2)):
        state = client.post(
            f"/api/sequences/{sequence['id']}/clips",
            json={"track_id": track["id"], "asset_id": asset["id"], "timeline_start": start,
                  "src_in": 0, "src_out": src_out},
        ).json()
    return state, video_clips(state)


def video_clips(sequence: dict) -> list[dict]:
    return sorted(
        next(t for t in sequence["tracks"] if t["kind"] == "video")["clips"],
        key=lambda c: c["timeline_start"],
    )


def test_ripple_delete_closes_gap_and_undoes() -> None:
    client = fresh_client()
    sequence, clips = setup_three_clips(client)
    middle = clips[1]  # B @5 len 3

    state = client.delete(f"/api/sequences/{sequence['id']}/clips/{middle['id']}/ripple").json()
    remaining = video_clips(state)
    assert [c["timeline_start"] for c in remaining] == [0, 7]  # C shifted 10 → 7

    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert [c["timeline_start"] for c in video_clips(undone)] == [0, 5, 10]

    redone = client.post(f"/api/sequences/{sequence['id']}/redo").json()
    assert [c["timeline_start"] for c in video_clips(redone)] == [0, 7]


def test_ripple_delete_clamps_overlapping_follower() -> None:
    client = fresh_client()
    sequence, clips = setup_three_clips(client)
    first = clips[0]  # A @0 len 4; B @5 would land at max(0, 5-4)=1, C at max(0, 10-4)=6

    state = client.delete(f"/api/sequences/{sequence['id']}/clips/{first['id']}/ripple").json()
    assert [c["timeline_start"] for c in video_clips(state)] == [1, 6]


def test_ripple_delete_last_clip_shifts_nothing() -> None:
    client = fresh_client()
    sequence, clips = setup_three_clips(client)
    last = clips[2]

    state = client.delete(f"/api/sequences/{sequence['id']}/clips/{last['id']}/ripple").json()
    assert [c["timeline_start"] for c in video_clips(state)] == [0, 5]
