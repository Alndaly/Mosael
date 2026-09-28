"""把素材转成某家供应商肯收的格式 —— 数字人那几家(可灵、HeyGen)各只收几种音频 / 图片格式。

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
