"""片段投影的偏移与模糊 —— 和前端跑**同一份**语料(contracts/clip-shadow-cases.json)。

前端 features/editor/playback/clipShadow.parity.test.ts 读同一个文件,断言预览 canvas 上投影落在哪、糊多少。
这里**真渲一帧**(render_still,和成片同一条滤镜图),从像素里量回偏移和 σ,和语料比 —— 不看滤镜串里写了
什么数字:此前导出把投影画在元素自己的坐标里、再跟着 scale / rotation 一起缩放旋转,滤镜串里的数字是对的,
画面上的投影却只有预览的几分之一。

画面:黑底,正中一块红色元素,投影是不透明的白。红的外框就是元素;白的外框减去红的外框是偏移;
模糊时红块外一圈渐隐的白,逐行积分出 σ(高斯阶跃边的外侧积分 = σ / √(2π))。
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.core.config import settings
from app.media.render_executor import render_still
from app.media.render_plan import build_render_plan

CONTRACT = json.loads((Path(__file__).parents[2] / "contracts" / "clip-shadow-cases.json").read_text())
HAS_FFMPEG = shutil.which(settings.ffmpeg) is not None


def test_语料在_且带版本() -> None:
    assert CONTRACT["contract"] == "clip-shadow"
    assert CONTRACT["version"] == 1
    assert CONTRACT["cases"]


WIDTH, HEIGHT = CONTRACT["frame"]["width"], CONTRACT["frame"]["height"]


def _sources(tmp_path: Path) -> dict[str, dict]:
    """黑底和红色元素各一段两秒的素材。"""
    for name in ("black", "red"):
        src = tmp_path / f"{name}.mp4"
        if not src.exists():
            subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
                            f"color={name}:s={WIDTH}x{HEIGHT}:r=10:d=2", "-pix_fmt", "yuv420p", str(src)],
                           check=True, timeout=30)
    return {"k": {"file_key": "black.mp4"}, "r": {"file_key": "red.mp4"}}


def _still(tmp_path: Path, plan, at: float) -> np.ndarray:
    frame = tmp_path / f"frame-{at}.png"
    render_still(plan, lambda key: tmp_path / key, frame, at)
    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(frame), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True, timeout=30).stdout
    return np.frombuffer(raw, np.uint8).reshape(HEIGHT, WIDTH, 3).astype(float)


def _render(tmp_path: Path, case: dict) -> np.ndarray:
    shadow = {"enabled": True, "color": "#ffffff", "opacity": 1.0, **case["shadow"]}
    plan = build_render_plan(
        sequence_id="s", revision=1, width=WIDTH, height=HEIGHT, fps=10,
        clips=[{"id": "b", "asset_id": "k", "timeline_start": 0, "src_in": 0, "src_out": 2}],
        assets=_sources(tmp_path),
        overlay_clips=[{"id": "o", "asset_id": "r", "timeline_start": 0, "src_in": 0, "src_out": 2,
                        "transform": case["transform"], "effects": {"appearance": {"shadow": shadow}}}],
    )
    return _still(tmp_path, plan, 1.0)


def _red(rgb: np.ndarray) -> np.ndarray:
    return (rgb[..., 0] > 150) & (rgb[..., 1] < 90) & (rgb[..., 2] < 90)


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _offset(rgb: np.ndarray, want: dict) -> tuple[int, int]:
    """白(投影露出来的那部分)的外框比红(元素)的外框多出去多少。往哪个方向偏,就量哪一边的边。"""
    red = _bbox(_red(rgb))
    white = _bbox(rgb.min(axis=2) > 150)
    dx = white[2] - red[2] if want["x"] >= 0 else white[0] - red[0]
    dy = white[3] - red[3] if want["y"] >= 0 else white[1] - red[1]
    return dx, dy


def _sigma(rgb: np.ndarray) -> float:
    """红块左右两侧那一圈白,逐行积分。只取远离上下角的行 —— 角上两条边的渐隐叠在一起。"""
    red = _red(rgb)
    x0, y0, x1, y1 = _bbox(red)
    margin = (y1 - y0) // 4
    shade = rgb[..., 1] / 255.0  # 投影是白、元素是红:绿通道里只有投影
    estimates = []
    for y in range(y0 + margin, y1 - margin):
        right = shade[y, x1 + 1:].sum()
        left = shade[y, :x0].sum()
        estimates += [right, left]
    return float(np.median(estimates)) * math.sqrt(2 * math.pi)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
@pytest.mark.parametrize("case", CONTRACT["cases"], ids=[case["name"] for case in CONTRACT["cases"]])
def test_真渲出来的投影和语料一致(case: dict, tmp_path: Path) -> None:
    rgb = _render(tmp_path, case)
    want = case["expected"]
    if case["shadow"]["blur"] == 0:
        got = _offset(rgb, want["offset_px"])
        assert got == pytest.approx((want["offset_px"]["x"], want["offset_px"]["y"]), abs=2), (
            f"{case['name']}:成片里投影偏了 {got},预览是 {want['offset_px']}"
        )
    else:
        sigma = _sigma(rgb)
        assert sigma == pytest.approx(want["sigma_px"], rel=0.1), (
            f"{case['name']}:成片里投影的 σ 是 {sigma:.2f},预览是 {want['sigma_px']}"
        )


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_缩放关键帧中途_底轨片段的投影偏移也还是画面像素(tmp_path: Path) -> None:
    """语料走的是上层片段、静态变换。底轨片段是另一条滤镜路,缩放打了关键帧时元素每一帧大小都不同 ——
    投影画在画幅大小的底板上,不受这个影响:放大前后两帧,偏移都是写的那个数。"""
    shadow = {"enabled": True, "color": "#ffffff", "opacity": 1.0, "blur": 0, "offset_x": 20, "offset_y": 12}
    plan = build_render_plan(
        sequence_id="s", revision=1, width=WIDTH, height=HEIGHT, fps=10,
        clips=[{"id": "b", "asset_id": "r", "timeline_start": 0, "src_in": 0, "src_out": 2,
                "transform": {"keyframes": [{"t": 0, "scale": 0.3}, {"t": 1, "scale": 0.6}]},
                "effects": {"appearance": {"shadow": shadow}}}],
        assets=_sources(tmp_path),
    )
    sizes = []
    for at in (0.3, 1.6):
        rgb = _still(tmp_path, plan, at)
        x0, _, x1, _ = _bbox(_red(rgb))
        sizes.append(x1 - x0)
        assert _offset(rgb, {"x": 20, "y": 12}) == pytest.approx((20, 12), abs=2), f"第 {at} 秒"
    assert sizes[1] > sizes[0] * 1.5, f"元素没在放大:{sizes}"
