"""短时频谱:`rhythm`、`timbre`、`sections` 共用的那一次 STFT。

输入是 22.05 kHz 单声道(`Pcm.mono_22k`)。窗 2048(约 93 ms,低频分得开)、跳 512(约 23 ms,一秒 43 帧,
够分出 200 BPM 的十六分音符)。
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property

import numpy as np

RATE = 22_050
WINDOW = 2048
HOP = 512


@dataclass(frozen=True)
class Spectrum:
    #: (帧数, WINDOW // 2 + 1) 的幅度谱。
    magnitude: np.ndarray

    @property
    def frames_per_second(self) -> float:
        return RATE / HOP

    @cached_property
    def frequencies(self) -> np.ndarray:
        return np.fft.rfftfreq(WINDOW, d=1 / RATE)

    @cached_property
    def power(self) -> np.ndarray:
        return self.magnitude**2

    @cached_property
    def frame_energy(self) -> np.ndarray:
        return self.power.sum(axis=1)

    def frame_time(self, index: int | np.ndarray) -> float | np.ndarray:
        return index * HOP / RATE


def spectrum(mono_22k: np.ndarray) -> Spectrum:
    if len(mono_22k) < WINDOW:
        mono_22k = np.pad(mono_22k, (0, WINDOW - len(mono_22k)))
    count = 1 + (len(mono_22k) - WINDOW) // HOP
    frames = np.lib.stride_tricks.as_strided(
        mono_22k, shape=(count, WINDOW), strides=(mono_22k.strides[0] * HOP, mono_22k.strides[0]), writeable=False
    )
    return Spectrum(magnitude=np.abs(np.fft.rfft(frames * np.hanning(WINDOW), axis=1)).astype(np.float32))
