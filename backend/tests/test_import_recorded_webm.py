"""MediaRecorder 直录 webm 的导入修复:流式写出的容器没有 Duration 头,
探不到时长、缩略图/剪辑随之失灵 — 导入管线应无损 remux 补头后重探。"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from tests.util import fresh_client

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _durationless_recording() -> bytes:
    """管道写出的 VP8 webm:muxer 无法回填 Duration 头,与 MediaRecorder 同形。"""
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=10",
            "-c:v", "libvpx", "-f", "webm", "pipe:1",
        ],
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:  # 精简版 ffmpeg 没有 libvpx
        pytest.skip("ffmpeg lacks libvpx")
    assert proc.stdout
    return proc.stdout


def test_recorded_webm_gains_duration_and_thumbnail() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    payload = _durationless_recording()
    created = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"], "name": "摄像头-测试"},
        files={"file": ("摄像头-测试.webm", payload, "video/webm")},
    )
    assert created.status_code == 200, created.text
    info = created.json()["media_info"]

    # remux 修复后必须有时长(≈1s),缩略图也应生成。
    assert info.get("duration") == pytest.approx(1.0, abs=0.35), info
    assert info.get("has_thumbnail") is True, info
