"""电平:多响、破没破音、左右声道是不是一回事。

整体响度、响度范围、真峰值交给 ffmpeg 的 EBU R128 实现(`app.media.loudness`,和铺配乐定增益同一份);
这里只量样本层面它不报的几样。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.media.listening.decode import Pcm

#: 到这个幅度就算顶到头了(float 解码后满幅是 1.0;编码器的取整会让削掉的平顶落在 0.999 上下)。
CLIP_LEVEL = 0.999
#: 连续这么多个样本顶在满幅才算削波:单个样本碰到满幅是正常的峰,连着几个是波形被削平了。
CLIP_RUN = 3


@dataclass(frozen=True)
class Levels:
    sample_peak_db: float
    rms_db: float
    #: 被削平的段落的起点(秒)。
    clipped_at: list[float]
    dc_offset: float
    #: 左右声道的相关系数:≈1 是单声道,<0 说明有反相,手机外放(单声道)时会互相抵消。
    channel_correlation: float | None


def db(value: float) -> float:
    return float(20 * np.log10(max(value, 1e-9)))


def levels(pcm: Pcm) -> Levels:
    samples = pcm.samples
    peak = float(np.abs(samples).max())
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    return Levels(
        sample_peak_db=round(db(peak), 2),
        rms_db=round(db(rms), 2),
        clipped_at=_clipped_runs(samples, pcm.rate),
        dc_offset=round(float(np.abs(samples.mean(axis=0)).max()), 4),
        channel_correlation=_correlation(samples),
    )


def _clipped_runs(samples: np.ndarray, rate: int) -> list[float]:
    hot = (np.abs(samples) >= CLIP_LEVEL).any(axis=1).astype(np.int8)
    if not hot.any():
        return []
    edges = np.diff(np.concatenate(([0], hot, [0])))
    starts, ends = np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)
    return [round(start / rate, 2) for start, end in zip(starts, ends, strict=True) if end - start >= CLIP_RUN]


def _correlation(samples: np.ndarray) -> float | None:
    left, right = samples[:, 0].astype(np.float64), samples[:, 1].astype(np.float64)
    if left.std() < 1e-6 or right.std() < 1e-6:
        return None
    return round(float(np.corrcoef(left, right)[0, 1]), 3)
