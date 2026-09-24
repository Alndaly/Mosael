"""浏览器录的参考音频,长度要量真的 —— 不能因为容器头没写就当成 0 秒。

用户:「参考音频明明不止0s」。配音区「上传克隆」里点「录制」,录了好几秒
(`recording-….webm`,68 KB),点「克隆」却被拒:「参考音频太短(只有 0.0 秒)」。

MediaRecorder 的 webm 是流式写出的,Chromium 不回填 Duration 头;ffprobe 的
`format.duration` 于是缺席,而调用处写的是 `probe_media(...).get("duration") or 0.0`
—— 「量不到」被读成了「0 秒」。素材导入那条路早就知道这件事(见 importer 的 remux 修复),
可修复只长在那一条路上;参考音频、听写直接拿临时文件去量,照样读到 0。

所以时长的兜底放在**量时长的那一处**(media/probe.probe_media):头里没有,就逐包读到最后
一包。谁来量,都量得到。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.media.probe import probe_media
from tests.util import fresh_client

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def _recording(seconds: float) -> bytes:
    """写到管道里的 webm/opus:muxer 回不了头,Duration 缺席 —— 与 MediaRecorder 直录同形。"""
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=frequency=220:duration={seconds}",
         "-c:a", "libopus", "-f", "webm", "pipe:1"],
        capture_output=True,
        timeout=60,
    )
    if proc.returncode != 0:  # 精简版 ffmpeg 没有 libopus
        pytest.skip("ffmpeg lacks libopus")
    assert proc.stdout
    return proc.stdout


def _header_has_no_duration(path: Path) -> bool:
    proc = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=20,
    )
    return proc.stdout.strip() in {"", "N/A"}


def test_a_headerless_recording_is_measured_not_zero(tmp_path: Path) -> None:
    source = tmp_path / "recording-1790270272478.webm"
    source.write_bytes(_recording(7))
    # 前提:它确实是用户那种「头里没写时长」的文件,否则这条测试什么也没证明。
    assert _header_has_no_duration(source)

    assert probe_media(source).get("duration") == pytest.approx(7.0, abs=0.2)


def test_the_clone_dialog_accepts_a_long_enough_recording() -> None:
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    resp = client.post(
        "/api/voices/upload",
        data={"workspace_id": workspace_id, "name": "录的", "reference_text": ""},
        files={"file": ("recording-1790270272478.webm", _recording(7), "audio/webm")},
    )

    assert resp.status_code == 200, resp.text


def test_a_short_recording_is_refused_with_its_real_length() -> None:
    """拒绝里的数字要是真的:录了 2 秒就说 2 秒,而不是 0.0。"""
    client = fresh_client()
    workspace_id = client.post("/api/workspaces", json={"name": "W"}).json()["id"]

    resp = client.post(
        "/api/voices/upload",
        data={"workspace_id": workspace_id, "name": "太短", "reference_text": ""},
        files={"file": ("recording-1790270272478.webm", _recording(2), "audio/webm")},
    )

    assert resp.status_code == 422, resp.text
    detail = resp.json()["detail"]
    assert "2.0" in detail, detail
    assert "0.0" not in detail, detail


def test_a_still_image_still_has_no_duration(tmp_path: Path) -> None:
    """图片的头里也没有时长,但它是一帧,不是一段 —— 兜底不能给它编出个 0.04 秒。"""
    image = tmp_path / "still.png"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=32x32", "-frames:v", "1", str(image)],
        check=True, capture_output=True, timeout=60,
    )

    assert "duration" not in probe_media(image)
