"""听一段声音:量出它的电平、连贯性、节奏、音色和起落,得出一份有时间点的问题清单(ADR 0103)。

纯测量,不碰数据库:输入一个文件路径(音频,或者视频 —— 取音轨)和可选的 [start, end)。
同一个文件、同一个窗口、同一个 `MEASURE_VERSION` 永远得出同一份报告,调用方据此缓存。

    report = listen(path, start=0, end=None, expect="music")
    png = spectrogram_png(path)

各模块各管一样(见各自的说明):`decode` 解码,`levels` 电平,`gaps` 连贯性,`spectrum` 共用的 STFT,
`rhythm` 节奏,`timbre` 音色,`sections` 起落,`findings` 问题清单,`spectrogram` 频谱图,`compare` 比较。
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.media.listening.compare import compare
from app.media.listening.decode import MAX_SECONDS, ListeningError, decode
from app.media.listening.findings import Expect, findings
from app.media.listening.gaps import gaps
from app.media.listening.levels import levels
from app.media.listening.rhythm import rhythm
from app.media.listening.sections import sections
from app.media.listening.spectrogram import spectrogram_png
from app.media.listening.spectrum import spectrum
from app.media.listening.timbre import timbre
from app.media.loudness import measure_loudness

#: 测量的算法或阈值一变就加一:缓存按它失效。
MEASURE_VERSION = 1


def listen(path: Path, *, start: float = 0.0, end: float | None = None, expect: Expect = "any") -> dict[str, Any]:
    pcm = decode(path, start=start, end=end)
    seconds = round(pcm.seconds, 2)
    spec = spectrum(pcm.mono_22k)
    loud = measure_loudness(path, start=start, seconds=pcm.seconds)
    level, gap, tone = levels(pcm), gaps(pcm), timbre(spec, pcm.mono_22k)
    return {
        "seconds": seconds,
        "window": [round(start, 2), round(start + seconds, 2)],
        "expect": expect,
        "loudness": asdict(loud) if loud else {"integrated": None, "range_lu": None, "true_peak": None},
        "levels": asdict(level),
        "gaps": asdict(gap),
        "rhythm": asdict(rhythm(spec)),
        "timbre": asdict(tone),
        "sections": [asdict(one) for one in sections(spec, pcm.seconds)],
        "findings": [asdict(one) for one in findings(loud, level, gap, tone, seconds=seconds, expect=expect)],
    }


__all__ = ["MAX_SECONDS", "MEASURE_VERSION", "Expect", "ListeningError", "compare", "listen", "spectrogram_png"]
