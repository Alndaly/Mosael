"""MediaRecorder 直录 webm 的导入修复:流式写出的容器没有 Duration 头,
探不到时长、缩略图/剪辑随之失灵 — 导入管线应无损 remux 补头后重探。"""

from __future__ import annotations

import shutil
import subprocess

import pytest

from tests.util import fresh_client

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _durationless_recording(*, audio: bool = False) -> bytes:
    """管道写出的 webm(视频 VP8 / 音频 Opus):muxer 无法回填 Duration 头,
    与 MediaRecorder 直录同形。"""
    source = (
        ["-f", "lavfi", "-i", "sine=frequency=440:duration=1", "-c:a", "libopus"]
        if audio
        else ["-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=10", "-c:v", "libvpx"]
    )
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", *source, "-f", "webm", "pipe:1"],
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:  # 精简版 ffmpeg 没有 libvpx/libopus
        pytest.skip("ffmpeg lacks libvpx/libopus")
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


def test_recorded_audio_webm_gains_duration_and_waveform() -> None:
    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    payload = _durationless_recording(audio=True)
    created = client.post(
        "/api/assets/import",
        data={"workspace_id": ws["id"], "name": "录音-测试"},
        files={"file": ("录音-测试.webm", payload, "audio/webm")},
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["kind"] == "audio"
    info = body["media_info"]
    assert info.get("duration") == pytest.approx(1.0, abs=0.35), info
    assert info.get("has_waveform") is True, info


def test_startup_reconcile_repairs_legacy_recordings() -> None:
    """remux 修复上线前入库的坏素材(缺时长)由启动兜底补修。"""
    from app.core.db import SessionLocal
    from app.domain.assets import reconcile_broken_media_info
    from app.media.paths import resolve_key

    client = fresh_client()
    ws = client.post("/api/workspaces", json={"name": "W"}).json()

    # 直接落一个坏文件 + 缺时长的 DB 行,模拟旧版导入结果。
    from app.core.config import settings

    media = settings.media_dir / "legacy-rec"
    media.mkdir(parents=True, exist_ok=True)
    (media / "cam.webm").write_bytes(_durationless_recording())
    created = client.post(
        "/api/assets",
        json={"workspace_id": ws["id"], "kind": "video", "name": "旧摄像头", "file_key": "media/legacy-rec/cam.webm"},
    ).json()
    assert created["media_info"].get("duration") is None

    with SessionLocal() as db:
        assert reconcile_broken_media_info(db) == 1

    repaired = client.get(f"/api/assets?workspace_id={ws['id']}").json()[0]
    info = repaired["media_info"]
    assert info.get("duration") == pytest.approx(1.0, abs=0.35), info
    assert info.get("has_thumbnail") is True, info
    assert resolve_key("media/legacy-rec/cam.webm").is_file()
