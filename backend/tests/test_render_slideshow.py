"""回归:带动画(Ken Burns/淡入)的多图片幻灯片导出。

历史 bug:带 transform 的元素合成到一张 **无时长** 的 color=black 背景上(无限流),
concat 永远停在第 0 段推不动,整条 filtergraph 疯狂缓冲——导出慢到 0.0x,且只有第一段
画面出得来。修复:给背景 :d=segment.duration。本测试同时验证「多段各自出画」与「时长正确」。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.media import render_executor as rx
from app.media.render_plan import build_render_plan

HAS_FFMPEG = shutil.which("ffmpeg") is not None
KEN_BURNS = {"keyframes": [{"t": 0, "scale": 1.0, "opacity": 0.0}, {"t": 1, "scale": 1.2, "opacity": 1.0}]}


def _solid(path: Path, color: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s=640x360", "-frames:v", "1", str(path)],
        check=True, timeout=30,
    )


def _pixel(path: Path, at: float) -> tuple[int, int, int]:
    out = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", str(at), "-i", str(path), "-frames:v", "1",
         "-vf", "scale=1:1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True, timeout=60,
    ).stdout
    return out[0], out[1], out[2]


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_animated_multiclip_slideshow_renders_each_clip(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(rx.settings, "hw_encode", False)
    red, green = tmp_path / "red.png", tmp_path / "green.png"
    _solid(red, "red")
    _solid(green, "green")
    # 两段各带 Ken Burns + 淡入:红 [0,2s]、绿 [2,4s]。
    plan = build_render_plan(
        sequence_id="s", revision=1, width=640, height=360, fps=30,
        clips=[
            {"id": "c0", "asset_id": "r", "timeline_start": 0, "src_in": 0, "src_out": 2, "transform": KEN_BURNS},
            {"id": "c1", "asset_id": "g", "timeline_start": 2, "src_in": 0, "src_out": 2, "transform": KEN_BURNS},
        ],
        assets={"r": {"file_key": str(red)}, "g": {"file_key": str(green)}},
    )
    out = tmp_path / "out.mp4"
    rx.execute_render(plan, lambda key: Path(key), out)  # 修复前这里会疯狂缓冲、久久不返回
    assert out.exists() and out.stat().st_size > 0

    dur = float(subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)],
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout.strip())
    assert abs(dur - 4.0) < 0.2

    # 关键:第二段必须真的出画。淡入到 ~1.5s 已接近满不透明。
    r1, g1, b1 = _pixel(out, 1.5)   # 第一段:红
    r2, g2, b2 = _pixel(out, 3.5)   # 第二段:绿(旧 bug 下会仍是红——concat 卡在第 0 段)
    assert r1 > g1 and r1 > b1, f"clip0 should be red, got ({r1},{g1},{b1})"
    assert g2 > r2 and g2 > b2, f"clip1 should be green, got ({r2},{g2},{b2})"
