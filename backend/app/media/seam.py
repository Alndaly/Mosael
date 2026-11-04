"""两段视频接在哪:上一段的末帧,在下一段开头哪一帧上。

续写的成片以上一段的尾巴开头,但这段尾巴的长度不可靠:万相 2.7 把 2 秒的尾巴压进了约 1.85 秒(2026-11-04 真机),
H3 的重叠区按 17k+5 帧取整。按秒数截就多截或少截几帧,接缝处跳一下。所以比画面:把两边都缩成很小的灰度图,
取最像的那一帧。一次 ffmpeg 读完,不落文件。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from app.core.child_process import run_logged
from app.core.config import settings
from app.core.i18n import LocalizedError

#: 比画面用的小图。够分出构图,抖动和压缩噪声又都被平均掉了。
_WIDTH, _HEIGHT = 96, 54


class SeamError(LocalizedError, ValueError):
    """找不到接缝。带文案 key。"""


def _frames(args: list[str], what: str) -> np.ndarray:
    try:
        done = run_logged(
            [settings.ffmpeg, "-v", "error", *args, "-vf", f"scale={_WIDTH}:{_HEIGHT}", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            check=True, capture_output=True, timeout=120, what=what,
        )
    except subprocess.SubprocessError as exc:
        raise SeamError("seamErr_unreadable") from exc
    size = _WIDTH * _HEIGHT
    count = len(done.stdout) // size
    if not count:
        raise SeamError("seamErr_unreadable")
    return np.frombuffer(done.stdout[: count * size], np.uint8).reshape(count, size).astype(np.float32)


def find_seam(previous: Path, following: Path, *, search_seconds: float, fps: float) -> float:
    """`following` 从第几秒开始是新内容:紧跟在和 `previous` 末帧最像的那一帧后面。"""
    #: 只读最后半秒,取最后一帧:`-sseof` 比整段解码快得多。
    last = _frames(["-sseof", "-0.5", "-i", str(previous)], "读上一段末帧")[-1]
    opening = _frames(["-t", f"{search_seconds:.3f}", "-i", str(following)], "读下一段开头")
    best = int(np.abs(opening - last).mean(axis=1).argmin())
    return (best + 1) / fps


__all__ = ["SeamError", "find_seam"]
