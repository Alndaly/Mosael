from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core.db import Base, engine, init_db
from app.main import app


def reset_db(tmp_path: Path) -> None:
    Base.metadata.drop_all(bind=engine)
    init_db()


def test_workspace_project_asset_sequence_clip_flow(tmp_path: Path) -> None:
    reset_db(tmp_path)
    client = TestClient(app)

    ws = client.post("/api/workspaces", json={"name": "Workspace"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "Project"}).json()
    asset = client.post(
        "/api/assets",
        json={
            "workspace_id": ws["id"],
            "project_id": project["id"],
            "kind": "video",
            "name": "Clip source",
            "original_filename": "clip.mp4",
            "file_key": "media/clip.mp4",
            "media_info": {"duration": 6},
        },
    ).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"},
    ).json()

    assert sequence["revision"] == 1
    assert [track["kind"] for track in sequence["tracks"]] == ["video", "audio"]

    video_track = next(track for track in sequence["tracks"] if track["kind"] == "video")
    updated = client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={
            "track_id": video_track["id"],
            "asset_id": asset["id"],
            "timeline_start": 0,
            "src_in": 0,
            "src_out": 6,
        },
    ).json()

    assert updated["revision"] == 2
    updated_video = next(track for track in updated["tracks"] if track["kind"] == "video")
    assert len(updated_video["clips"]) == 1
    assert updated_video["clips"][0]["asset_id"] == asset["id"]


def test_import_uploaded_asset_creates_file_backed_asset(tmp_path: Path) -> None:
    reset_db(tmp_path)
    client = TestClient(app)

    ws = client.post("/api/workspaces", json={"name": "Workspace"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "Project"}).json()
    res = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"], "project_id": project["id"], "name": "Poster"},
        files={"file": ("poster.png", b"not-a-real-png-but-file-backed", "image/png")},
    )

    assert res.status_code == 200
    asset = res.json()
    assert asset["kind"] == "image"
    assert asset["source"] == "imported"
    assert asset["name"] == "Poster"
    assert asset["file_key"].endswith("/poster.png")
