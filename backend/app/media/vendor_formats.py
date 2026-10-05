"""把素材转成某家供应商肯收的格式 —— 数字人那几家(可灵、HeyGen)各只收几种音频 / 图片格式,百炼改口型只收每边
640–2048 像素的视频。

哪几种算「肯收」由各家适配器按自己的文档判,这里只管转:配音是说话,转成单声道 64kbps mp3 足够清楚,
体积也小(300 秒约 2.4MB,放得进可灵 5MB 的上限);图片取第一帧存成 png。
"""

from __future__ import annotations

from pathlib import Path

from app.core.child_process import run_logged
from app.core.config import settings
from app.core.i18n import LocalizedError, tr
from app.core.text import blame_line


class VendorFormatError(LocalizedError, RuntimeError):
    """转不出来。带文案 key,可以直接给用户看。"""


def _convert(arguments: list[str], target: Path, what: str) -> Path:
    result = run_logged([settings.ffmpeg, "-y", "-v", "error", *arguments, str(target)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300, what=what)
    if result.returncode != 0 or not target.is_file():
        raise VendorFormatError("mediaErr_vendorFormat", what=what,
                                detail=blame_line(result.stderr, fallback="") or tr("audioErr_ffmpegNoReason"))
    return target


def speech_mp3(source: Path, target: Path) -> Path:
    """一段配音(或带声音的视频)→ 单声道 64kbps 的 mp3。"""
    return _convert(["-i", str(source), "-vn", "-ac", "1", "-b:a", "64k"], target, "配音转 mp3")


def still_png(source: Path, target: Path) -> Path:
    """一张图(webp、heic 之类)→ png。"""
    return _convert(["-i", str(source), "-frames:v", "1"], target, "图片转 png")


def video_sides_within(source: Path, target: Path, *, min_side: int, max_side: int) -> Path:
    """一段视频的宽、高都放进 `[min_side, max_side]` 像素:放得下就原样交回 `source`;放不下就等比缩放(往上或往下)
    一份到 `target`,宽高取偶数(H.264 的要求)。等比怎么缩都放不进(长宽比太极端)时说清楚。

    百炼改口型只收每边 640–2048 像素的原视频,而说话照片交回的是 512×512 —— 两步接起来就被拒(真跑撞上过)。
    """
    from app.media.probe import probe_media

    info = probe_media(source, measure_missing_duration=False)
    width, height = int(info.get("width") or 0), int(info.get("height") or 0)
    if width <= 0 or height <= 0:
        return source
    short, long = min(width, height), max(width, height)
    if short >= min_side and long <= max_side:
        return source
    scale = min_side / short if short < min_side else max_side / long
    if short * scale < min_side - 0.5 or long * scale > max_side + 0.5:
        raise VendorFormatError(
            "mediaErr_videoSidesOutOfRange", width=width, height=height, min=min_side, max=max_side,
        )
    new_width, new_height = (max(2, int(round(side * scale / 2)) * 2) for side in (width, height))
    return _convert(
        ["-i", str(source), "-vf", f"scale={new_width}:{new_height}", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac"],
        target, "视频缩放到供应商收的尺寸",
    )
