"""输入级 -ss 快进优化:深处剪片段不再从第 0 帧解码,且保持帧精确。"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.media import render_executor as rx
from app.media.render_executor import build_ffmpeg_command
from app.media.render_plan import build_render_plan

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def test_seek_and_trim_skips_small_offsets():
    # 入点浅(图片/从头的片段,或快进点退半秒后已经到头)不加 -ss,trim 保持原样。
    assert rx._seek_and_trim(0.0, 5.0) == ([], 0.0, 5.0)
    assert rx._seek_and_trim(0.01, 5.0) == ([], 0.01, 5.0)
    assert rx._seek_and_trim(0.5, 5.0) == ([], 0.5, 5.0)


def test_seek_and_trim_fast_forwards_deep_cuts():
    seek, tin, tout = rx._seek_and_trim(10.0, 12.5)
    #: 快进到入点前半秒(声音解码器要前一帧才收敛,见 _SEEK_PREROLL),trim 从那里切到入点。
    assert seek == ["-ss", "9.500000"]
    assert tin == 0.5
    assert tout == 3.0  # 长度不变


def test_build_command_emits_input_seek_before_input_for_deep_clip():
    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=[{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 10, "src_out": 12}],
        assets={"a": {"file_key": "/does-not-exist.mp4"}},
    )
    cmd = build_ffmpeg_command(plan, lambda k: Path(k), Path("/tmp/out.mp4"))
    assert "-ss" in cmd
    # -ss 必须在它对应的 -i 之前才是输入级快进
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-ss") + 1] == "9.500000"
    # trim 从快进点算起
    assert "trim=start=0.5:end=2.5" in " ".join(cmd)


def test_build_command_no_seek_for_from_start_clip():
    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=[{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 2}],
        assets={"a": {"file_key": "/does-not-exist.mp4"}},
    )
    cmd = build_ffmpeg_command(plan, lambda k: Path(k), Path("/tmp/out.mp4"))
    assert "-ss" not in cmd  # 从头的片段行为完全不变


def _first_pixel_rgb(path: Path, at: float) -> tuple[int, int, int]:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1",
         "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True, timeout=60,
    ).stdout
    return out[0], out[1], out[2]


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_deep_clip_stays_frame_accurate(tmp_path: Path, monkeypatch):
    """源:前 3s 红、后 3s 绿。剪 [4,6] 应得 2s 纯绿——证明 -ss 精确落到 src_in 而非从 0 起。"""
    monkeypatch.setattr(rx.settings, "hw_encode", False)  # 软件编码,输出确定
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "color=c=red:s=320x180:d=3:r=30",
         "-f", "lavfi", "-i", "color=c=green:s=320x180:d=3:r=30",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p[v]",
         "-map", "[v]", "-c:v", "libx264", "-g", "15", str(src)],
        check=True, timeout=60,
    )
    plan = build_render_plan(
        sequence_id="s", revision=1, width=320, height=180, fps=30,
        clips=[{"id": "c1", "asset_id": "a", "timeline_start": 0, "src_in": 4, "src_out": 6}],
        assets={"a": {"file_key": str(src)}},
    )
    out = tmp_path / "out.mp4"
    rx.execute_render(plan, lambda key: Path(key), out)
    assert out.exists() and out.stat().st_size > 0

    # 时长应为 2s(trim 长度正确)
    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout.strip())
    assert abs(dur - 2.0) < 0.2

    # 中间帧应为绿(G 主导);若 -ss 落错、从 0 帧解码则会是红。
    r, g, b = _first_pixel_rgb(out, 1.0)
    assert g > r and g > b, f"expected green, got rgb=({r},{g},{b})"


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_入点落在关键帧上_声音不缺头(tmp_path: Path, monkeypatch):
    """快进点正好落在关键帧上时,各路从快进点起解,声音解码器的头一帧没有前一帧可叠:入点开头几十毫秒的
    声音和源对不上(一声「咔」)。底轨、上层轨、音频轨走的是同一个快进,这里用音频轨的一段量。"""
    import numpy as np

    monkeypatch.setattr(rx.settings, "hw_encode", False)
    src = tmp_path / "src.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=64x36:r=30:d=8",
         "-f", "lavfi", "-i", "sine=f=440:r=48000:d=8", "-shortest",
         "-c:v", "libx264", "-preset", "ultrafast", "-g", "60", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)],
        check=True, timeout=60,
    )
    plan = build_render_plan(
        sequence_id="s", revision=1, width=64, height=36, fps=30,
        clips=[{"id": "v", "asset_id": "a", "timeline_start": 0, "src_in": 0, "src_out": 3}],
        audio_clips=[{"id": "m", "asset_id": "a", "timeline_start": 1.0, "src_in": 4.0, "src_out": 6.0, "gain": 1.0}],
        assets={"a": {"file_key": str(src)}},
        mute_base_audio=True,
    )
    out = tmp_path / "out.mp4"
    rx.execute_render(plan, lambda key: Path(key), out)

    def pcm(path: Path) -> np.ndarray:
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a", "-ac", "1", "-ar", "48000",
                              "-f", "f32le", "-"], capture_output=True, check=True, timeout=60).stdout
        return np.frombuffer(raw, np.float32)

    sound, source = pcm(out), pcm(src)
    window = int(0.04 * 48000)
    error = float(np.sqrt(np.mean((sound[48000:48000 + window] - source[4 * 48000:4 * 48000 + window]) ** 2)))
    signal = float(np.sqrt(np.mean(source ** 2)))
    assert error < signal * 0.05, f"入点开头 40 毫秒的声音和源对不上(误差 {error:.4f},信号 {signal:.4f})"
