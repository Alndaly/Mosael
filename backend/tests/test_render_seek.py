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
    # src_in≈0(图片/从头的片段)不加 -ss,trim 保持原样。
    assert rx._seek_and_trim(0.0, 5.0) == ([], 0.0, 5.0)
    assert rx._seek_and_trim(0.01, 5.0) == ([], 0.01, 5.0)


def test_seek_and_trim_fast_forwards_deep_cuts():
    seek, tin, tout = rx._seek_and_trim(10.0, 12.5)
    assert seek == ["-ss", "10.000000"]
    assert tin == 0.0
    assert tout == 2.5  # 长度不变,起点归零


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
    assert cmd[cmd.index("-ss") + 1] == "10.000000"
    # trim 改成从 0 起算
    assert "trim=start=0.0:end=2.0" in " ".join(cmd)


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
