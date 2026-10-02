"""烧字的两条真路,给要「真渲一遍文字」的测试挑:

- `use_libass(monkeypatch)`:走 ASS(libass)。配置的 ffmpeg 没有 libass 就跳过 —— Homebrew 的 core ffmpeg
  就没有;本机想跑,用 MOSAEL_FFMPEG 指到完整版(如 /opt/homebrew/opt/ffmpeg-full/bin/ffmpeg)。
- `use_browser(monkeypatch)`:走无头 Chromium 按预览 CSS 渲 PNG。找不到前端 dist 或 Chromium 起不来就跳过;
  本机想跑,用 MOSAEL_FRONTEND_DIST 指到一份构建好的 frontend/dist。

两条路都**不打桩**:要证明的正是真 ffmpeg / 真浏览器画出来的东西。
"""

from __future__ import annotations

import functools

import pytest

from app.core.config import settings
from app.media.render_executor import ffmpeg_has_libass


def use_libass(monkeypatch) -> None:
    if not ffmpeg_has_libass(settings.ffmpeg):
        pytest.skip(f"{settings.ffmpeg} has no libass")
    monkeypatch.setattr(settings, "text_rasterize", False)


@functools.cache
def _browser_works() -> bool:
    from app.media.render_plan import DEFAULT_SUBTITLE_STYLE
    from app.media.text_render import TextRasterizer, find_frontend_dist

    if find_frontend_dist() is None:
        return False
    try:
        with TextRasterizer(64, 64) as rasterizer:
            rasterizer.render_subtitle("x", DEFAULT_SUBTITLE_STYLE)
    except Exception:  # noqa: BLE001 — 起不来就是这台机器没有这条路
        return False
    return True


def use_browser(monkeypatch) -> None:
    if not _browser_works():
        pytest.skip("frontend dist / Chromium not available")
    monkeypatch.setattr(settings, "text_rasterize", True)
