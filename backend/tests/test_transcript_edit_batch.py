"""Transcript-driven multi-clip gestures are one atomic timeline operation.

The editor can select transcript ranges that span several clips.  That is one user gesture,
so it must create one revision and one undo step rather than issuing one operation per clip.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from tests.util import fresh_client


def _setup_two_clips(client: TestClient) -> tuple[dict, list[dict]]:
    workspace = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post(
        "/api/projects",
        json={"workspace_id": workspace["id"], "name": "P"},
    ).json()
    asset = client.post(
        "/api/assets",
        json={
            "workspace_id": workspace["id"],
            "project_id": project["id"],
            "kind": "video",
            "name": "S",
            "file_key": "media/s.mp4",
            "media_info": {"duration": 20},
        },
    ).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": workspace["id"], "project_id": project["id"], "name": "Main"},
    ).json()
    track = next(track for track in sequence["tracks"] if track["kind"] == "video")
    for timeline_start in (0, 12):
        sequence = client.post(
            f"/api/sequences/{sequence['id']}/clips",
            json={
                "track_id": track["id"],
                "asset_id": asset["id"],
                "timeline_start": timeline_start,
                "src_in": 0,
                "src_out": 10,
            },
        ).json()
    return sequence, _video_clips(sequence)


def _video_clips(sequence: dict) -> list[dict]:
    return sorted(
        next(track for track in sequence["tracks"] if track["kind"] == "video")["clips"],
        key=lambda clip: clip["timeline_start"],
    )


def test_cutting_ranges_across_clips_is_one_revision_and_one_undo() -> None:
    client = fresh_client()
    sequence, clips = _setup_two_clips(client)

    edited = client.post(
        f"/api/sequences/{sequence['id']}/clips/cut-ranges",
        json={
            "cuts": [
                {"clip_id": clips[0]["id"], "ranges": [{"src_start": 2, "src_end": 4}]},
                {"clip_id": clips[1]["id"], "ranges": [{"src_start": 6, "src_end": 8}]},
            ],
        },
    )

    assert edited.status_code == 200, edited.text
    assert edited.json()["revision"] == sequence["revision"] + 1
    assert len(_video_clips(edited.json())) == 4

    undone = client.post(f"/api/sequences/{sequence['id']}/undo")
    assert undone.status_code == 200, undone.text
    restored = _video_clips(undone.json())
    assert [(clip["id"], clip["src_in"], clip["src_out"]) for clip in restored] == [
        (clips[0]["id"], 0, 10),
        (clips[1]["id"], 0, 10),
    ]

    redone = client.post(f"/api/sequences/{sequence['id']}/redo")
    assert redone.status_code == 200, redone.text
    assert len(_video_clips(redone.json())) == 4


def test_cutting_ranges_rolls_back_every_clip_when_one_cut_is_invalid() -> None:
    client = fresh_client()
    sequence, clips = _setup_two_clips(client)

    rejected = client.post(
        f"/api/sequences/{sequence['id']}/clips/cut-ranges",
        json={
            "cuts": [
                {"clip_id": clips[0]["id"], "ranges": [{"src_start": 2, "src_end": 4}]},
                {"clip_id": "missing-clip", "ranges": [{"src_start": 6, "src_end": 8}]},
            ],
        },
    )

    assert rejected.status_code == 404
    current = client.get(f"/api/sequences/{sequence['id']}").json()
    assert current["revision"] == sequence["revision"]
    assert [(clip["id"], clip["src_in"], clip["src_out"]) for clip in _video_clips(current)] == [
        (clips[0]["id"], 0, 10),
        (clips[1]["id"], 0, 10),
    ]


def test_splitting_points_across_clips_is_one_revision_and_one_undo() -> None:
    client = fresh_client()
    sequence, clips = _setup_two_clips(client)

    edited = client.post(
        f"/api/sequences/{sequence['id']}/clips/split-points",
        json={
            "splits": [
                {"clip_id": clips[0]["id"], "src_times": [2, 4]},
                {"clip_id": clips[1]["id"], "src_times": [6, 8]},
            ],
        },
    )

    assert edited.status_code == 200, edited.text
    assert edited.json()["revision"] == sequence["revision"] + 1
    assert len(_video_clips(edited.json())) == 6

    undone = client.post(f"/api/sequences/{sequence['id']}/undo")
    assert undone.status_code == 200, undone.text
    restored = _video_clips(undone.json())
    assert [(clip["id"], clip["src_in"], clip["src_out"]) for clip in restored] == [
        (clips[0]["id"], 0, 10),
        (clips[1]["id"], 0, 10),
    ]

    redone = client.post(f"/api/sequences/{sequence['id']}/redo")
    assert redone.status_code == 200, redone.text
    assert len(_video_clips(redone.json())) == 6
