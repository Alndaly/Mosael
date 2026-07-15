from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import Base, engine, init_db
from app.main import app

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def make_test_video(path: Path, seconds: float) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", f"testsrc2=size=320x180:rate=30:duration={seconds}",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            str(path),
        ],
        check=True,
        timeout=60,
    )


def test_export_renders_mp4_with_gap_black(tmp_path: Path) -> None:
    Base.metadata.drop_all(bind=engine)
    init_db()
    client = TestClient(app)

    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()

    source = tmp_path / "src.mp4"
    make_test_video(source, 1.0)
    asset = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"], "project_id": project["id"]},
        files={"file": ("src.mp4", source.read_bytes(), "video/mp4")},
    ).json()

    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main", "width": 320, "height": 180},
    ).json()
    video_track = next(track for track in sequence["tracks"] if track["kind"] == "video")
    for start in (0.0, 1.5):  # 0.5s gap between the two clips
        client.post(
            f"/api/sequences/{sequence['id']}/clips",
            json={"track_id": video_track["id"], "asset_id": asset["id"], "timeline_start": start, "src_in": 0, "src_out": 1.0},
        )

    job = client.post(f"/api/sequences/{sequence['id']}/export").json()
    assert job["kind"] == "render"

    deadline = time.time() + 90
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.5)

    assert job["status"] == "succeeded", job.get("error")
    assert job["progress"] == 1.0

    output = settings.data_dir / "exports" / f"{job['id']}.mp4"
    assert output.exists()

    exported_asset = client.get(f"/api/assets?workspace_id={ws['id']}").json()
    exported = next(item for item in exported_asset if item["source"] == "exported")
    assert exported["kind"] == "video"
    assert abs(exported["media_info"]["duration"] - 2.5) < 0.2


def test_export_empty_sequence_rejected() -> None:
    Base.metadata.drop_all(bind=engine)
    init_db()
    client = TestClient(app)
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"},
    ).json()
    res = client.post(f"/api/sequences/{sequence['id']}/export")
    assert res.status_code == 422
