"""分享预览图(Open Graph,1200×630):快照里最多 4 张图的拼贴 + 标题 + Mosael 字标。

第一次有人请求时由服务端从快照生成,存进对象存储(`og/<版本 id>.png`),之后直接给存好的那张。
画板每发一个新版本,预览图跟着新版本重新生成(旧版本的那张不动 —— 快照不可变,它的预览图也不变)。
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from community.logs import log_event

logger = logging.getLogger(__name__)

WIDTH, HEIGHT = 1200, 630
BACKGROUND = (15, 15, 20)
PANEL = (28, 28, 36)
TITLE = (245, 245, 250)
MUTED = (160, 160, 175)
PADDING = 48
GAP = 12

#: 找不到配置的字体时按顺序试这些位置(容器里装的是 Noto CJK)。
FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
)

# Pillow 对解不开的超大图会报 DecompressionBombError;预览图只取缩略图,给一个宽松但有限的上限。
Image.MAX_IMAGE_PIXELS = 80_000_000


def _font(path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in (path, *FONT_CANDIDATES):
        if candidate and Path(candidate).is_file():
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
    return ImageFont.load_default(size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int, max_lines: int) -> list[str]:
    """按像素宽度折行(中文没有空格,逐字量)。超出行数的最后一行加省略号。"""
    lines: list[str] = []
    current = ""
    for char in text:
        if char == "\n":
            lines.append(current)
            current = ""
            continue
        trial = current + char
        if draw.textlength(trial, font=font) <= width:
            current = trial
        else:
            lines.append(current)
            current = char
        if len(lines) >= max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and "".join(lines) != text.replace("\n", ""):
        last = lines[-1]
        while last and draw.textlength(last + "…", font=font) > width:
            last = last[:-1]
        lines[-1] = last + "…"
    return [line for line in lines if line.strip()] or [text[:1]]


def _open_image(data: bytes) -> Image.Image | None:
    try:
        image = Image.open(io.BytesIO(data))
        image.draft("RGB", (800, 800))
        image = ImageOps.exif_transpose(image)
        return image.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return None


def render_og(
    *,
    title: str,
    author: str,
    images: list[Callable[[], bytes | None]],
    wordmark_path: str,
    font_path: str = "",
) -> bytes:
    """画一张预览图。`images` 是最多 4 个「读出图片字节」的函数(读失败的跳过)。"""
    canvas = Image.new("RGB", (WIDTH, HEIGHT), BACKGROUND)
    draw = ImageDraw.Draw(canvas)

    tiles: list[Image.Image] = []
    for load in images[:4]:
        try:
            data = load()
        except Exception as exc:  # noqa: BLE001 - 一张图读不出来不该让整张预览图失败
            log_event(logger, "og image source unreadable", logging.WARNING, error=type(exc).__name__)
            data = None
        image = _open_image(data) if data else None
        if image is not None:
            tiles.append(image)

    text_left = PADDING
    if tiles:
        area = HEIGHT - 2 * PADDING
        grid_left = WIDTH - PADDING - area
        cells = {1: [(0, 0, 2, 2)], 2: [(0, 0, 1, 2), (1, 0, 1, 2)], 3: [(0, 0, 1, 2), (1, 0, 1, 1), (1, 1, 1, 1)]}.get(
            len(tiles), [(0, 0, 1, 1), (1, 0, 1, 1), (0, 1, 1, 1), (1, 1, 1, 1)]
        )
        unit = (area - GAP) / 2
        for tile, (col, row, span_w, span_h) in zip(tiles, cells):
            width = int(unit * span_w + GAP * (span_w - 1))
            height = int(unit * span_h + GAP * (span_h - 1))
            fitted = ImageOps.fit(tile, (width, height), method=Image.Resampling.LANCZOS)
            canvas.paste(fitted, (int(grid_left + col * (unit + GAP)), int(PADDING + row * (unit + GAP))))
        text_width = grid_left - PADDING - text_left
    else:
        draw.rounded_rectangle((PADDING, PADDING, WIDTH - PADDING, HEIGHT - PADDING), radius=24, fill=PANEL)
        text_left = PADDING * 2
        text_width = WIDTH - 4 * PADDING

    title_font = _font(font_path, 60)
    meta_font = _font(font_path, 30)
    lines = _wrap(draw, title.strip() or "Mosael", title_font, int(text_width), 4)
    y = PADDING * 2
    for line in lines:
        draw.text((text_left, y), line, font=title_font, fill=TITLE)
        y += 76
    if author:
        draw.text((text_left, y + 16), author, font=meta_font, fill=MUTED)

    try:
        with Image.open(wordmark_path) as mark:
            mark = mark.convert("RGBA")
            target_width = min(int(text_width), 300)
            scaled = mark.resize((target_width, max(1, int(mark.height * target_width / mark.width))), Image.Resampling.LANCZOS)
            canvas.paste(scaled, (text_left, HEIGHT - PADDING * 2 - scaled.height + (PADDING if tiles else 0)), scaled)
    except (OSError, ValueError):
        draw.text((text_left, HEIGHT - PADDING * 2), "Mosael", font=meta_font, fill=TITLE)

    out = io.BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    return out.getvalue()


__all__ = ["HEIGHT", "WIDTH", "render_og"]
