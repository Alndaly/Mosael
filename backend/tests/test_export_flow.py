from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.db import Base, engine
from app.db.migrations import init_db
from app.main import app
from tests.util import fresh_client

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
    client = fresh_client()

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


def test_export_video_on_overlay_track_renders_with_audio(tmp_path: Path) -> None:
    """Regression: after the z-order flip, a video on an upper track with an empty bottom track
    used to fail export ("no clips to render") and drop its audio. The base must be the
    bottom-most track WITH clips, and the overlay video's audio must be mixed in."""
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    source = tmp_path / "src.mp4"
    make_test_video(source, 1.5)
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
    client.post(
        f"/api/sequences/{sequence['id']}/clips",
        json={"track_id": video_track["id"], "asset_id": asset["id"], "timeline_start": 0, "src_in": 0, "src_out": 1.5},
    )
    # Add a second video track — it becomes the (empty) bottom "base"; the clip is now an overlay.
    client.post(f"/api/sequences/{sequence['id']}/tracks", json={"kind": "video"})

    job = client.post(f"/api/sequences/{sequence['id']}/export").json()
    deadline = time.time() + 90
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job['id']}").json()
        if job["status"] in {"succeeded", "failed"}:
            break
        time.sleep(0.5)
    assert job["status"] == "succeeded", job.get("error")

    output = settings.data_dir / "exports" / f"{job['id']}.mp4"
    streams = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(output)],
        capture_output=True, text=True,
    ).stdout
    assert "video" in streams and "audio" in streams  # the overlay video's audio survived export


def test_export_empty_sequence_rejected() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()
    project = client.post("/api/projects", json={"workspace_id": ws["id"], "name": "P"}).json()
    sequence = client.post(
        "/api/sequences",
        json={"workspace_id": ws["id"], "project_id": project["id"], "name": "Main"},
    ).json()
    res = client.post(f"/api/sequences/{sequence['id']}/export")
    assert res.status_code == 422


def test_friendly_render_error_names_corrupt_input() -> None:
    """导出失败时把 ffmpeg「打不开输入文件」翻成点名素材的中文(修复 code 187 无信息问题)。"""
    from app.domain.render import _friendly_render_error
    from app.media.render_executor import RenderExecutionError

    tail = (
        "[in#4] 0x00 at pos 36 invalid as first byte of an EBML number\n"
        "Error opening input file /Users/x/.open-studio/media/assets/w/a/摄像头-1784712022145.webm.\n"
        "Error opening input files: End of file\n"
    )
    msg = _friendly_render_error(RenderExecutionError("FFmpeg exited with code 187", stderr_tail=tail))
    assert "摄像头-1784712022145.webm" in msg and "损坏或未录制完整" in msg

    # 认不出具体文件但有损坏迹象 → 泛化提示
    msg2 = _friendly_render_error(RenderExecutionError("FFmpeg exited with code 1", stderr_tail="moov atom not found"))
    assert "损坏或未录制完整" in msg2

    # 完全认不出 → 退回原始错误
    msg3 = _friendly_render_error(RenderExecutionError("FFmpeg exited with code 8", stderr_tail="weird"))
    assert "code 8" in msg3
