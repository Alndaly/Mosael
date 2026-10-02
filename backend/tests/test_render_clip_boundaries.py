"""相邻两段的交界帧只属于后一段:叠层的 enable 是右开的 [start, end)。

此前是 `between(t,start,end)`,两端都闭 —— 交界那一帧前后两段都画:
- 两条相邻字幕在交界帧叠在一起;
- 上层视频还带 eof_action=repeat,上一段在交界帧把它的末帧再画一遍,
  后一段若是画中画,它底下露出上一段整幅的最后一帧。

真 ffmpeg 渲出来,逐帧读像素。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.core.config import settings
from app.media.render_executor import _subtitle_overlay_pos, build_ffmpeg_command, compose_text_layers
from app.media.render_plan import build_render_plan

pytestmark = pytest.mark.skipif(shutil.which(settings.ffmpeg) is None, reason="ffmpeg not installed")

W, H, FPS = 160, 90, 10


def _make(path: Path, *lavfi: str) -> None:
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", *[a for src in lavfi for a in ("-f", "lavfi", "-i", src)],
                    "-pix_fmt", "yuv420p", str(path)], check=True, timeout=30)


def _frames(path: Path) -> np.ndarray:
    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True, timeout=60).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W, 3).astype(int)


def _is(pixel: np.ndarray, rgb: tuple[int, int, int]) -> bool:
    return bool(np.abs(pixel - np.array(rgb)).max() < 60)


def test_上层视频的交界帧只画后一段(tmp_path) -> None:
    _make(tmp_path / "green.mp4", f"color=0x00ff00:s={W}x{H}:r={FPS}:d=4")
    _make(tmp_path / "red.mp4", f"color=0xff0000:s={W}x{H}:r={FPS}:d=2")
    _make(tmp_path / "blue.mp4", f"color=0x0000ff:s={W}x{H}:r={FPS}:d=2")
    plan = build_render_plan(
        sequence_id="s", revision=1, width=W, height=H, fps=FPS,
        clips=[{"id": "base", "asset_id": "g", "timeline_start": 0, "src_in": 0, "src_out": 4}],
        assets={"g": {"file_key": "green.mp4"}, "r": {"file_key": "red.mp4"}, "b": {"file_key": "blue.mp4"}},
        overlay_clips=[
            {"id": "a", "asset_id": "r", "timeline_start": 0, "src_in": 0, "src_out": 2},
            # 后一段是右下角一个小画中画:它四周该露出底下的绿,而不是前一段整幅的红。
            {"id": "b", "asset_id": "b", "timeline_start": 2, "src_in": 0, "src_out": 2,
             "transform": {"scale": 0.3, "x": 0.6, "y": 0.6}},
        ],
    )
    out = tmp_path / "out.mp4"
    subprocess.run(build_ffmpeg_command(plan, lambda key: tmp_path / key, out, force_software=True),
                   check=True, capture_output=True, timeout=60)
    frames = _frames(out)
    boundary = 2 * FPS
    assert _is(frames[boundary - 1][10, 10], (255, 0, 0)), "交界前一帧还是前一段"
    assert _is(frames[boundary][10, 10], (0, 255, 0)), "交界帧不该再画前一段(的末帧)"
    assert _is(frames[boundary][int(H * 0.8), int(W * 0.8)], (0, 0, 255)), "交界帧是后一段"


def test_相邻两条字幕_交界帧只有后一条(tmp_path) -> None:
    _make(tmp_path / "black.mp4", f"color=black:s={W}x{H}:r={FPS}:d=4")
    # 前一条是一块大的红,后一条是一块小的蓝:交界帧要是两条都画,蓝的四周会露出红边。
    first, second = tmp_path / "sub0.png", tmp_path / "sub1.png"
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "color=0xff0000:s=80x20",
                    "-frames:v", "1", str(first)], check=True, timeout=30)
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "color=0x0000ff:s=40x10",
                    "-frames:v", "1", str(second)], check=True, timeout=30)
    plan = build_render_plan(
        sequence_id="s", revision=1, width=W, height=H, fps=FPS,
        clips=[{"id": "base", "asset_id": "k", "timeline_start": 0, "src_in": 0, "src_out": 4}],
        assets={"k": {"file_key": "black.mp4"}},
        subtitle_clips=[
            {"id": "s1", "asset_id": None, "timeline_start": 0, "src_in": 0, "src_out": 2, "text_override": "一"},
            {"id": "s2", "asset_id": None, "timeline_start": 2, "src_in": 0, "src_out": 2, "text_override": "二"},
        ],
    )
    out = tmp_path / "out.mp4"
    pngs = {"subtitles": [(first, 80, 20), (second, 40, 10)], "text_overlays": []}
    layers = compose_text_layers(plan, pngs, tmp_path)
    subprocess.run(build_ffmpeg_command(plan, lambda key: tmp_path / key, out, force_software=True, text_layers=layers),
                   check=True, capture_output=True, timeout=60)
    frames = _frames(out)
    x, y = _subtitle_overlay_pos(plan.subtitle_style, 80, 20, W, H)
    corner = (y + 2, x + 2)  # 大红块的左上角:小蓝块盖不到这里
    boundary = 2 * FPS
    assert _is(frames[boundary - 1][corner], (255, 0, 0)), "交界前一帧是前一条"
    assert _is(frames[boundary][corner], (0, 0, 0)), "交界帧两条字幕叠在一起了"
