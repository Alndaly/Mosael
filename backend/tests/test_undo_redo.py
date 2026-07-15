from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.db import Base, engine, init_db
from app.main import app
from tests.util import fresh_client


def setup_sequence(client: TestClient) -> tuple[dict, dict, dict]:
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    asset = client.post(
        "/api/assets",
        json={
            "workspace_id": ws["id"],
            "project_id": project["id"],
            "kind": "video",
            "name": "Src",
            "file_key": "media/src.mp4",
            "media_info": {"duration": 10},
        },
    ).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"},
    ).json()
    return ws, asset, sequence


def video_clips(sequence: dict) -> list[dict]:
    return next(track for track in sequence["tracks"] if track["kind"] == "video")["clips"]


def insert(client: TestClient, sequence: dict, asset: dict, start: float) -> dict:
    track = next(track for track in sequence["tracks"] if track["kind"] == "video")
    return client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": track["id"], "asset_id": asset["id"], "timeline_start": start, "src_in": 0, "src_out": 5},
    ).json()


def reset() -> TestClient:
    return fresh_client()


def test_undo_insert_removes_clip_and_redo_restores(tmp_path: Path) -> None:
    client = reset()
    _, asset, sequence = setup_sequence(client)
    state = insert(client, sequence, asset, 0)
    assert state["can_undo"] is True and state["can_redo"] is False

    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert video_clips(undone) == []
    assert undone["can_redo"] is True

    redone = client.post(f"/api/sequences/{sequence['id']}/redo").json()
    assert len(video_clips(redone)) == 1
    assert redone["can_undo"] is True and redone["can_redo"] is False


def test_undo_move_and_trim_restore_previous_values(tmp_path: Path) -> None:
    client = reset()
    _, asset, sequence = setup_sequence(client)
    state = insert(client, sequence, asset, 0)
    clip = video_clips(state)[0]

    client.patch(f"/api/sequences/{sequence['id']}/clips/{clip['id']}/move", json={"timeline_start": 3})
    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert video_clips(undone)[0]["timeline_start"] == 0

    client.patch(
        f"/api/sequences/{sequence['id']}/clips/{clip['id']}/trim",
        json={"timeline_start": 0, "src_in": 1, "src_out": 4},
    )
    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    restored = video_clips(undone)[0]
    assert restored["src_in"] == 0 and restored["src_out"] == 5


def test_undo_delete_restores_clip_with_same_id(tmp_path: Path) -> None:
    client = reset()
    _, asset, sequence = setup_sequence(client)
    state = insert(client, sequence, asset, 0)
    clip = video_clips(state)[0]

    client.delete(f"/api/sequences/{sequence['id']}/clips/{clip['id']}")
    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert video_clips(undone)[0]["id"] == clip["id"]


def test_new_edit_after_undo_invalidates_redo(tmp_path: Path) -> None:
    client = reset()
    _, asset, sequence = setup_sequence(client)
    insert(client, sequence, asset, 0)
    client.post(f"/api/sequences/{sequence['id']}/undo")
    state = insert(client, sequence, asset, 6)
    assert state["can_redo"] is False
    res = client.post(f"/api/sequences/{sequence['id']}/redo")
    assert res.status_code == 422


def test_multiple_undos_walk_back_in_lifo_order(tmp_path: Path) -> None:
    client = reset()
    _, asset, sequence = setup_sequence(client)
    insert(client, sequence, asset, 0)
    state = insert(client, sequence, asset, 6)
    assert len(video_clips(state)) == 2

    one = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert len(video_clips(one)) == 1
    assert video_clips(one)[0]["timeline_start"] == 0

    zero = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert video_clips(zero) == []
    assert zero["can_undo"] is False

    empty = client.post(f"/api/sequences/{sequence['id']}/undo")
    assert empty.status_code == 422


def test_revision_increments_on_undo_and_redo(tmp_path: Path) -> None:
    client = reset()
    _, asset, sequence = setup_sequence(client)
    state = insert(client, sequence, asset, 0)
    assert state["revision"] == 2
    undone = client.post(f"/api/sequences/{sequence['id']}/undo").json()
    assert undone["revision"] == 3
    redone = client.post(f"/api/sequences/{sequence['id']}/redo").json()
    assert redone["revision"] == 4
