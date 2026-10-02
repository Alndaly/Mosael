"""「AI 生成」显式标识压在纯黑、纯白的画面上都读得出,角标按边距贴着右上角、长文字不被裁。

此前标识借的是花字的样子(白字 + 黑描边):浏览器的描边骑在字形轮廓上画,一半压进字里,小字号下黑边把
白芯吃掉大半 —— 压在深色画面上几乎看不见;角标的锚点是元素**中心**放在 x=0.91w,英文「AI-generated」
在 720 宽的竖屏里右半截出了画面。

两条烧字路(libass、浏览器渲 PNG)都真渲一帧,读像素:
- 读得出:标识范围里有足够多的亮像素(白字),白底上它们被一圈暗像素(底框)包着;
- 贴边:角标底框的右边、上边离画面边缘 margin(按画幅短边算),且整块在画面里。
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
from tests.render_text_paths import use_browser, use_libass

pytestmark = pytest.mark.skipif(shutil.which(settings.ffmpeg) is None, reason="ffmpeg not installed")

FRAMES = [(1080, 1920, "AI 生成"), (720, 1280, "AI-generated"), (1920, 1080, "AI-generated")]


def _still(tmp_path: Path, width: int, height: int, background: str, text: str) -> np.ndarray:
    src = tmp_path / f"{background}.mp4"
    if not src.exists():
        subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi",
                        "-i", f"color={background}:s={width}x{height}:r=10:d=5", "-pix_fmt", "yuv420p", str(src)],
                       check=True, timeout=60)
    plan = build_render_plan(
        sequence_id="s", revision=1, width=width, height=height, fps=10,
        clips=[{"id": "c", "asset_id": "v", "timeline_start": 0, "src_in": 0, "src_out": 5}],
        assets={"v": {"file_key": src.name}}, ai_label=text,
    )
    frame = tmp_path / f"{background}.png"
    render_still(plan, lambda key: tmp_path / key, frame, 1.0)
    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(frame), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True, timeout=30).stdout
    return np.frombuffer(raw, np.uint8).reshape(height, width).astype(int), plan


def _box(changed: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(changed)
    assert len(xs), "画面上找不到标识"
    return int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())


def _readable(gray: np.ndarray, background: str, font_size: float, text: str) -> None:
    """字要「亮且多」:亮像素(白字)的数量够一行粗体字的墨量;白底上它们外面还得有一圈暗(底框)。"""
    bg = 0 if background == "black" else 255
    x0, y0, x1, y1 = _box(np.abs(gray - bg) > 40)
    crop = gray[y0:y1 + 1, x0:x1 + 1]
    glyphs = len(text.replace(" ", ""))
    bright = int((crop > 200).sum())
    #: 粗体字的墨量大约是每个字 0.1~0.3 个字号见方;描边吃掉白芯的旧样子在黑底上只剩零头。
    assert bright >= 0.08 * font_size ** 2 * glyphs, f"白字太少({bright} 个亮像素),读不出"
    if background == "white":
        dark = int((crop < 160).sum())
        assert dark >= 0.3 * crop.size, "白底上白字外面没有底框,融进画面里了"


@pytest.mark.parametrize("path", ["libass", "browser"])
@pytest.mark.parametrize("background", ["black", "white"])
@pytest.mark.parametrize(("width", "height", "text"), FRAMES)
def test_标识在黑白画面上都读得出_角标贴着右上角不被裁(path, background, width, height, text, tmp_path, monkeypatch) -> None:
    (use_libass if path == "libass" else use_browser)(monkeypatch)
    gray, plan = _still(tmp_path, width, height, background, text)
    opening, corner = plan.ai_labels
    half_w, half_h = width // 2, height // 2

    # 角标:只看右上那一块(片头那块在正中,不在这里)
    region = gray[: half_h // 2, half_w:]
    _readable(region, background, corner.font_size, text)
    if background == "white":
        x0, y0, x1, y1 = _box(np.abs(region - 255) > 40)
        right, top = half_w + x1, y0
        tolerance = max(3, corner.font_size * 0.15)
        assert abs((width - 1 - right) - corner.margin) <= tolerance, f"右边距 {width - 1 - right},应为 {corner.margin}"
        assert abs(top - corner.margin) <= tolerance, f"上边距 {top},应为 {corner.margin}"
        assert half_w + x0 > width * 0.5, "角标太宽,伸到了画面左半边"

    # 片头那块:正中,整块在画面里
    middle = gray[height // 3: height * 2 // 3, :]
    _readable(middle, background, opening.font_size, text)
    x0, _y0, x1, _y1 = _box(np.abs(middle - (0 if background == "black" else 255)) > 40)
    assert x0 > 0 and x1 < width - 1, "片头那块被画面边缘裁掉了"
    assert abs((x0 + x1) / 2 - width / 2) <= max(4, width * 0.01), "片头那块不在正中"
