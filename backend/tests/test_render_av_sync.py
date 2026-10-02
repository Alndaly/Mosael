"""音轨比画面晚开始的素材,导出后声画仍然对得上。

AAC 的起始延迟、录屏、-itsoffset 过的文件,音轨的 start_time 常常是 0.2~0.5 秒。此前画面和声音各自
`PTS-STARTPTS`:两路的第一帧 / 第一个采样都被拽到 0,于是声音整段提前了它晚开始的那么多 —— 素材自己放
是对的,导出来口型对不上。走 -ss 快进的片段一样。

素材:画面在 1.0 / 2.48 秒各闪一下白,声音在**同样的绝对时间**各响一下;音轨用 -itsoffset 晚开始 0.5 秒。
真 ffmpeg 导出,再从成片里量每一次闪白和响声的时刻。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.core.config import settings
from app.media.render_executor import build_ffmpeg_command
from app.media.render_plan import build_render_plan

pytestmark = pytest.mark.skipif(shutil.which(settings.ffmpeg) is None, reason="ffmpeg not installed")

W, H, FPS, RATE = 64, 36, 25, 48000
FRAME = 1 / FPS


def _late_audio_source(path: Path) -> None:
    #: 闪两帧:变速 2 倍之后还剩一帧,量得到。
    flashes = "between(t,1,1.079)+between(t,2.48,2.559)"
    subprocess.run([
        settings.ffmpeg, "-y", "-v", "error",
        "-f", "lavfi", "-i", f"color=black:s={W}x{H}:r={FPS}:d=4[b];color=white:s={W}x{H}:r={FPS}:d=4[w];"
                             f"[b][w]overlay=enable='{flashes}'",
        # 音轨晚 0.5 秒开始;它自己的 0.5 / 1.98 秒就是绝对时间的 1.0 / 2.48 秒。
        "-itsoffset", "0.5", "-f", "lavfi",
        "-i", f"sine=f=1000:d=3.5:r={RATE},volume='if(between(t,0.5,0.55)+between(t,1.98,2.03),0.8,0)':eval=frame",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    ], check=True, timeout=30)


def _late_video_source(path: Path) -> None:
    """反过来:画面晚 0.5 秒开始(它自己的 0.5 秒是绝对时间的 1.0 秒),声音从 0 开始。"""
    subprocess.run([
        settings.ffmpeg, "-y", "-v", "error",
        "-itsoffset", "0.5", "-f", "lavfi",
        "-i", f"color=black:s={W}x{H}:r={FPS}:d=3.5[b];color=white:s={W}x{H}:r={FPS}:d=3.5[w];"
              f"[b][w]overlay=enable='between(t,0.5,0.579)+between(t,1.98,2.059)'",
        "-f", "lavfi",
        "-i", f"sine=f=1000:d=4:r={RATE},volume='if(between(t,1.0,1.05)+between(t,2.48,2.53),0.8,0)':eval=frame",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", str(path),
    ], check=True, timeout=30)


def _flashes(path: Path) -> list[float]:
    #: 同 _beeps:按时间戳把画面开头补齐(复制第一帧),量出来的是绝对时间。
    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(path), "-vf", f"fps={FPS}:start_time=0,scale=8:8",
                          "-f", "rawvideo", "-pix_fmt", "gray", "-"], capture_output=True, check=True, timeout=60).stdout
    bright = np.frombuffer(raw, np.uint8).reshape(-1, 64).mean(axis=1) > 128
    return [round(i * FRAME, 3) for i in range(len(bright)) if bright[i] and (i == 0 or not bright[i - 1])]


def _beeps(path: Path) -> list[float]:
    #: 读成裸采样会丢掉时间戳(第一个采样就是音轨的开头);按时间戳把开头补成静音,量出来的才是绝对时间。
    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(path), "-vn",
                          "-af", f"aresample={RATE}:min_comp=0.001:first_pts=0", "-ac", "1",
                          "-f", "f32le", "-"], capture_output=True, check=True, timeout=60).stdout
    samples = np.frombuffer(raw, np.float32)
    window = RATE // 500  # 2 ms
    loud = np.sqrt((samples[: len(samples) // window * window].reshape(-1, window) ** 2).mean(axis=1)) > 0.05
    return [round(i * window / RATE, 3) for i in range(len(loud)) if loud[i] and (i == 0 or not loud[i - 1])]


def _render(tmp_path: Path, **plan_kwargs) -> Path:
    plan = build_render_plan(sequence_id="s", revision=1, width=W, height=H, fps=FPS,
                             assets={"late": {"file_key": "late.mp4"}, "black": {"file_key": "black.mp4"}}, **plan_kwargs)
    out = tmp_path / "out.mp4"
    subprocess.run(build_ffmpeg_command(plan, lambda key: tmp_path / key, out, force_software=True),
                   check=True, capture_output=True, timeout=120)
    return out


def test_素材自己放_声画是对的(tmp_path) -> None:
    """护住前提:素材本身闪白和响声同时。"""
    _late_audio_source(tmp_path / "late.mp4")
    flashes, beeps = _flashes(tmp_path / "late.mp4"), _beeps(tmp_path / "late.mp4")
    assert len(flashes) == len(beeps) == 2
    assert all(abs(b - f) < FRAME * 1.2 for f, b in zip(flashes, beeps))


def test_基底轨上的片段_从头剪和快进剪_声画都对得上(tmp_path) -> None:
    _late_audio_source(tmp_path / "late.mp4")
    out = _render(tmp_path, clips=[
        # 从头剪(src_in=0,不走 -ss)
        {"id": "a", "asset_id": "late", "timeline_start": 0, "src_in": 0, "src_out": 3, "has_audio": True},
        # 深一点剪(src_in>0.05,走输入级 -ss 快进);快进点 0.2 在音轨开始之前
        {"id": "b", "asset_id": "late", "timeline_start": 3, "src_in": 0.2, "src_out": 3.0, "has_audio": True},
        # 变速
        {"id": "c", "asset_id": "late", "timeline_start": 5.8, "src_in": 0, "src_out": 3, "speed": 2.0, "has_audio": True},
    ])
    flashes, beeps = _flashes(out), _beeps(out)
    expected = [1.0, 2.48, 3.8, 5.28, 6.3, 7.04]
    assert flashes == pytest.approx(expected, abs=FRAME * 1.2)
    assert beeps == pytest.approx(flashes, abs=FRAME * 1.2), f"声音和画面错开了:画面 {flashes} 声音 {beeps}"


def test_音频轨上的片段_落在它该在的时刻(tmp_path) -> None:
    _late_audio_source(tmp_path / "late.mp4")
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=black:s={W}x{H}:r={FPS}:d=6",
                    "-pix_fmt", "yuv420p", str(tmp_path / "black.mp4")], check=True, timeout=30)
    out = _render(tmp_path,
                  clips=[{"id": "base", "asset_id": "black", "timeline_start": 0, "src_in": 0, "src_out": 6}],
                  audio_clips=[
                      {"id": "x", "asset_id": "late", "timeline_start": 1, "src_in": 0, "src_out": 2, "gain": 1.0},
                      {"id": "y", "asset_id": "late", "timeline_start": 3.5, "src_in": 0.3, "src_out": 2.0, "gain": 1.0},
                  ])
    # 两段都只截到素材 1.0 秒那一响(2.48 那一响在截取范围外):
    # 第一段 → 时间线 1 + 1.0;第二段(走 -ss 快进)→ 时间线 3.5 + (1.0 - 0.3)
    assert _beeps(out) == pytest.approx([2.0, 4.2], abs=0.02)


def test_画面晚开始的素材_声画也对得上(tmp_path) -> None:
    _late_video_source(tmp_path / "late.mov")
    assert _flashes(tmp_path / "late.mov") == pytest.approx(_beeps(tmp_path / "late.mov"), abs=FRAME * 1.2)
    plan = build_render_plan(sequence_id="s", revision=1, width=W, height=H, fps=FPS,
                             assets={"late": {"file_key": "late.mov"}},
                             clips=[{"id": "a", "asset_id": "late", "timeline_start": 0, "src_in": 0, "src_out": 3,
                                     "has_audio": True},
                                    {"id": "b", "asset_id": "late", "timeline_start": 3, "src_in": 0.2, "src_out": 3,
                                     "has_audio": True}])
    out = tmp_path / "out.mp4"
    subprocess.run(build_ffmpeg_command(plan, lambda key: tmp_path / key, out, force_software=True),
                   check=True, capture_output=True, timeout=120)
    flashes, beeps = _flashes(out), _beeps(out)
    assert flashes == pytest.approx([1.0, 2.48, 3.8, 5.28], abs=FRAME * 1.2)
    assert beeps == pytest.approx(flashes, abs=FRAME * 1.2), f"声音和画面错开了:画面 {flashes} 声音 {beeps}"
