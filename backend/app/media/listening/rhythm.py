"""节奏:有没有稳定的拍子、多快。

起音强度包络(谱通量:每一帧比上一帧多出来的能量)做自相关,在 60–200 BPM 之间找最强的周期,
轻轻偏向 120 BPM(两倍、一半的速度自相关同样强,不偏的话常报成一半)。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.media.listening.spectrum import Spectrum

BPM_RANGE = (60.0, 200.0)
#: 自相关峰低于它就说没有稳定的拍子(念白、氛围音乐、乱的那种)。
STEADY_AT = 0.15


@dataclass(frozen=True)
class Rhythm:
    #: 没有稳定拍子时是 None。
    bpm: float | None
    #: 拍子有多稳:0(没有)到 1(节拍器)。
    steadiness: float


def rhythm(spectrum: Spectrum) -> Rhythm:
    flux = np.diff(np.log1p(spectrum.magnitude * 10), axis=0).clip(min=0).sum(axis=1)
    if len(flux) < spectrum.frames_per_second * 4:
        return Rhythm(bpm=None, steadiness=0.0)
    window = int(spectrum.frames_per_second)
    onset = flux - np.convolve(flux, np.ones(window) / window, mode="same")
    onset = onset.clip(min=0)
    spectrum_of = np.fft.rfft(onset, n=2 * len(onset))
    autocorr = np.fft.irfft(spectrum_of * np.conj(spectrum_of))[: len(onset)]
    if autocorr[0] <= 0:
        return Rhythm(bpm=None, steadiness=0.0)
    autocorr = autocorr / autocorr[0]
    fps = spectrum.frames_per_second
    lags = np.arange(int(fps * 60 / BPM_RANGE[1]), int(fps * 60 / BPM_RANGE[0]) + 1)
    bpms = fps * 60 / lags
    prior = np.exp(-0.5 * (np.log2(bpms / 120.0) / 1.0) ** 2)
    best = int(np.argmax(autocorr[lags] * prior))
    steadiness = float(max(0.0, autocorr[lags[best]]))
    lag = _refine(autocorr, int(lags[best]))
    return Rhythm(
        bpm=round(float(fps * 60 / lag), 1) if steadiness >= STEADY_AT else None,
        steadiness=round(min(1.0, steadiness), 2),
    )


def _refine(autocorr: np.ndarray, lag: int) -> float:
    """抛物线插值:整帧的滞后在 120 BPM 附近一帧差 3 BPM,插一下准到零点几。"""
    if lag <= 0 or lag + 1 >= len(autocorr):
        return float(lag)
    left, centre, right = autocorr[lag - 1], autocorr[lag], autocorr[lag + 1]
    bend = left - 2 * centre + right
    return lag + (0.5 * (left - right) / bend if bend else 0.0)
