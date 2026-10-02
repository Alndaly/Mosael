"""画面元素的大小和形状跟预览(scenePaint)一致:

- 上层片段(画中画)按素材**自己的宽高比**成元素 —— 竖素材在横画幅里做画中画就是竖的。此前先铺满再
  裁成画幅比例,竖的人像画中画在成片里成了一条横的;
- 底轨片段打了变换(缩放、关键帧)之后,contain / blur 的填充模式**还在**:contain 留边,blur 背后是
  同一段素材铺满再模糊。此前一律铺满裁满 —— 一打关键帧,画面就从留边跳成裁满;
- 有蒙版 / 投影的「自由元素」仍是画幅那么大(契约 clip-free-element-geometry 管的那一块,不动)。

真 ffmpeg 渲一帧,量红色那一块的外框。素材是 90×160 的纯红竖条,画幅 320×180。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.core.config import settings
from app.media.render_executor import render_still
from app.media.render_plan import build_render_plan

pytestmark = pytest.mark.skipif(shutil.which(settings.ffmpeg) is None, reason="ffmpeg not installed")

W, H = 320, 180


def _sources(tmp_path: Path) -> None:
    for name, spec in (("tall.mp4", "color=red:s=90x160"), ("grey.mp4", f"color=gray:s={W}x{H}"),
                       ("pattern.mp4", "testsrc2=s=90x160")):
        subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"{spec}:r=10:d=2",
                        "-pix_fmt", "yuv420p", str(tmp_path / name)], check=True, timeout=30)


def _frame(tmp_path: Path, name: str, **plan_kwargs) -> np.ndarray:
    plan = build_render_plan(sequence_id="s", revision=1, width=W, height=H, fps=10,
                             assets={"tall": {"file_key": "tall.mp4"}, "grey": {"file_key": "grey.mp4"},
                                     "pattern": {"file_key": "pattern.mp4"}}, **plan_kwargs)
    out = tmp_path / f"{name}.png"
    render_still(plan, lambda key: tmp_path / key, out, 1.0)
    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(out), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True, timeout=30).stdout
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3).astype(int)


def _red_box(rgb: np.ndarray) -> tuple[int, int]:
    """红色那一块的 (宽, 高)。"""
    ys, xs = np.nonzero((rgb[..., 0] > 180) & (rgb[..., 1] < 90) & (rgb[..., 2] < 90))
    return int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)


def _tall(asset: str = "tall", **extra) -> dict:
    return {"id": "t", "asset_id": asset, "timeline_start": 0, "src_in": 0, "src_out": 2, **extra}


def test_竖素材做横画幅的画中画_还是竖的(tmp_path) -> None:
    _sources(tmp_path)
    rgb = _frame(tmp_path, "pip", clips=[{"id": "g", "asset_id": "grey", "timeline_start": 0, "src_in": 0, "src_out": 2}],
                 overlay_clips=[_tall(transform={"scale": 0.3})])
    # 预览:cover = max(320/90, 180/160) → 320×568.9,再 ×0.3 → 96×170.7
    width, height = _red_box(rgb)
    assert width == pytest.approx(96, abs=3) and height == pytest.approx(171, abs=3), f"画中画是 {width}×{height}"


def test_画中画带投影时仍是画幅大小的自由元素(tmp_path) -> None:
    _sources(tmp_path)
    shadow = {"appearance": {"shadow": {"enabled": True, "opacity": 0.0}}}
    rgb = _frame(tmp_path, "free", clips=[{"id": "g", "asset_id": "grey", "timeline_start": 0, "src_in": 0, "src_out": 2}],
                 overlay_clips=[_tall(transform={"scale": 0.3}, effects=shadow)])
    assert _red_box(rgb) == pytest.approx((96, 54), abs=3), "自由元素按契约是画幅大小(铺满再裁)"


@pytest.mark.parametrize("fill_mode", ["contain", "blur"])
def test_留边和模糊背景的底轨_打了关键帧也不跳成裁满(fill_mode, tmp_path) -> None:
    _sources(tmp_path)
    # 缩放关键帧 1 → 1:画面上什么都不该变,只是这一段走了「带变换」那条路
    hold = {"transform": {"keyframes": [{"t": 0, "scale": 1}, {"t": 1, "scale": 1}]}}
    still = _frame(tmp_path, "still", clips=[_tall("pattern")], fill_mode=fill_mode)
    keyed = _frame(tmp_path, "keyed", clips=[_tall("pattern", **hold)], fill_mode=fill_mode)
    assert np.abs(still - keyed).mean() < 6, f"{fill_mode} 打了关键帧之后画面变了(跳成裁满)"
    if fill_mode == "contain":
        # 90×160 装进 320×180 → 101×180,两边是黑的
        assert _red_box(_frame(tmp_path, "red", clips=[_tall(**hold)], fill_mode="contain")) == pytest.approx((101, 180), abs=3)
        assert keyed[90, 10].max() < 30


def test_留边的底轨缩小之后_按装进画幅的大小缩(tmp_path) -> None:
    _sources(tmp_path)
    rgb = _frame(tmp_path, "small", clips=[_tall(transform={"scale": 0.8})], fill_mode="contain")
    assert _red_box(rgb) == pytest.approx((81, 144), abs=3)
