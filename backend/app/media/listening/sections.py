"""起落:每 2 秒一格,这一格多响、多亮。前奏、主歌、高潮、收尾在这串数里看得出来。"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.media.listening.spectrum import WINDOW, Spectrum

STEP_SECONDS = 2.0
#: 太长的片子格子放宽,一份报告最多这么多格 —— 交给模型的是走势,不是一张大表。
MAX_SECTIONS = 60
#: 一帧半边谱的总功率 → 这一帧的均方值(帕塞瓦尔:半边谱 ≈ N/2 · Σ(x·w)²,汉宁窗 Σw² = 3N/8)。
MEAN_SQUARE_PER_POWER = 16 / (3 * WINDOW**2)


@dataclass(frozen=True)
class Section:
    start: float
    #: 这一格的平均电平(dBFS,未加权)。
    level_db: float
    brightness_hz: float


def sections(spectrum: Spectrum, seconds: float) -> list[Section]:
    step = max(STEP_SECONDS, seconds / MAX_SECTIONS)
    per = max(1, int(round(step * spectrum.frames_per_second)))
    energy, freqs = spectrum.frame_energy, spectrum.frequencies
    out: list[Section] = []
    for first in range(0, len(energy), per):
        chunk = energy[first : first + per]
        power = spectrum.power[first : first + per]
        total = float(chunk.sum())
        level = 10 * np.log10(max(total / len(chunk) * MEAN_SQUARE_PER_POWER, 1e-18))
        out.append(Section(
            start=round(first / spectrum.frames_per_second, 1),
            level_db=round(float(level), 1),
            brightness_hz=round(float((power.sum(axis=0) * freqs).sum() / total), 1) if total > 0 else 0.0,
        ))
    return out
