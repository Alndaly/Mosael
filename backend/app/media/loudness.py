"""量一段音频的整体响度(EBU R128 integrated loudness,单位 LUFS)。

给「按听感定音量」的那几处用:铺配乐时按这首曲子实际多响来定它的增益,而不是乘一个固定倍数 ——
生成出来的曲子响度差得很远(同一个音乐模型,带人声的原曲 −16.5 LUFS,拆掉人声的伴奏 −22.8 LUFS),
固定倍数在轻的那首上就压没了。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from app.core.child_process import run_logged
from app.core.config import settings

#: ebur128 摘要里那一行:`I:         -22.8 LUFS`。
_INTEGRATED = re.compile(r"^\s*I:\s+(-?\d+(?:\.\d+)?)\s+LUFS", re.MULTILINE)
#: 低于它的算「没有声音」:ebur128 对整段静音报 −70(门限),这样的值拿来算增益会放大几千倍。
SILENT_BELOW = -60.0


def integrated_loudness(path: Path, *, seconds: float | None = None) -> float | None:
    """`path` 的整体响度(LUFS)。`seconds` = 只量开头这么长(实际会用到的那一段)。

    量不出来(文件读不了、整段静音)交回 None —— 调用方自己决定没量到时怎么办,这里不猜一个数。
    """
    window = ["-t", f"{seconds:.3f}"] if seconds else []
    try:
        result = run_logged(
            [settings.ffmpeg, "-hide_banner", "-nostats", *window, "-i", str(path), "-vn",
             "-af", "ebur128=framelog=quiet", "-f", "null", "-"],
            capture_output=True, text=True, timeout=300, what="测量响度", level=logging.DEBUG,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    found = _INTEGRATED.findall(result.stderr)
    if not found:
        return None
    loudness = float(found[-1])
    return loudness if loudness > SILENT_BELOW else None


__all__ = ["SILENT_BELOW", "integrated_loudness"]
