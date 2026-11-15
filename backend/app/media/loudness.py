"""量一段音频的响度(EBU R128:整体响度 LUFS、响度范围 LU、真峰值 dBTP)。

给「按听感定音量」的那几处用:铺配乐时按这首曲子实际多响来定它的增益,而不是乘一个固定倍数 ——
生成出来的曲子响度差得很远(同一个音乐模型,带人声的原曲 −16.5 LUFS,拆掉人声的伴奏 −22.8 LUFS),
固定倍数在轻的那首上就压没了。智能体「听」音频(`app.media.listening`,ADR 0103)也从这里取这三项。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from app.core.child_process import run_logged
from app.core.config import settings

#: ebur128 摘要里的三行:`I:  -22.8 LUFS`、`LRA:  6.1 LU`、`Peak:  -0.4 dBFS`(peak=true 时是真峰值)。
_INTEGRATED = re.compile(r"^\s*I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", re.MULTILINE)
_RANGE = re.compile(r"^\s*LRA:\s+(-?\d+(?:\.\d+)?)\s+LU\b", re.MULTILINE)
_TRUE_PEAK = re.compile(r"^\s*Peak:\s+(-?(?:\d+(?:\.\d+)?|inf))\s+dBFS", re.MULTILINE)
#: 低于它的算「没有声音」:ebur128 对整段静音报 −70(门限),这样的值拿来算增益会放大几千倍。
SILENT_BELOW = -60.0


@dataclass(frozen=True)
class Loudness:
    #: 整体响度(LUFS)。整段静音时是 None。
    integrated: float | None
    #: 响度范围(LU):这段声音有多大的起伏。
    range_lu: float | None
    #: 真峰值(dBTP):算上采样点之间的峰,超过 0 就会在播放端破音。
    true_peak: float | None


def measure_loudness(path: Path, *, start: float = 0.0, seconds: float | None = None) -> Loudness | None:
    """`path` 里 [start, start + seconds) 那一段的 EBU R128 测量。读不了交回 None,这里不猜一个数。"""
    window = [*(["-ss", f"{start:.3f}"] if start else []), *(["-t", f"{seconds:.3f}"] if seconds else [])]
    try:
        result = run_logged(
            [settings.ffmpeg, "-hide_banner", "-nostats", *window, "-i", str(path), "-vn",
             "-af", "ebur128=framelog=quiet:peak=true", "-f", "null", "-"],
            capture_output=True, text=True, timeout=300, what="测量响度", level=logging.DEBUG,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    integrated = _last(_INTEGRATED, result.stderr)
    if integrated is None:
        return None
    peak = _last(_TRUE_PEAK, result.stderr)
    return Loudness(
        integrated=integrated if integrated > SILENT_BELOW else None,
        range_lu=_last(_RANGE, result.stderr),
        true_peak=peak if peak is not None and peak > -200 else None,
    )


def integrated_loudness(path: Path, *, seconds: float | None = None) -> float | None:
    """`path` 的整体响度(LUFS)。`seconds` = 只量开头这么长(实际会用到的那一段)。

    量不出来(文件读不了、整段静音)交回 None —— 调用方自己决定没量到时怎么办,这里不猜一个数。
    """
    measured = measure_loudness(path, seconds=seconds)
    return measured.integrated if measured else None


def _last(pattern: re.Pattern[str], text: str) -> float | None:
    found = pattern.findall(text)
    return float(found[-1]) if found and found[-1] != "-inf" else None


__all__ = ["SILENT_BELOW", "Loudness", "integrated_loudness", "measure_loudness"]
