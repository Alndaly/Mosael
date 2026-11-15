"""音色:亮还是闷、像乐音还是像噪声、能量在低中高哪一段、(单一人声 / 独奏时)音高。

「两个声音差在哪」靠的就是这几样:明亮度(频谱质心)差一倍是一闷一亮;基频差一个八度上下是一男一女;
平坦度高是气声、沙哑或者干脆是噪声。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.media.listening.spectrum import RATE, Spectrum

BANDS = {"low": (0.0, 250.0), "mid": (250.0, 4000.0), "high": (4000.0, RATE / 2)}
#: 只看不安静的帧:比最响的那一帧低 50 dB 以内。
AUDIBLE_WITHIN_DB = 50.0
#: 基频:YIN,46 ms 一帧,60–1000 Hz;最多取 1500 帧(均匀抽),再长的片子音高统计也够了。
PITCH_FRAME = 1024
PITCH_RANGE = (60.0, 1000.0)
PITCH_MAX_FRAMES = 1500
YIN_THRESHOLD = 0.15


@dataclass(frozen=True)
class Timbre:
    #: 频谱质心(Hz):越高越亮。
    brightness_hz: float
    #: 85% 能量在这个频率以下(Hz)。
    rolloff_hz: float
    #: 谱平坦度 0–1:接近 0 是乐音,接近 1 是噪声。
    noisiness: float
    #: 低 / 中 / 高三段能量的占比,加起来是 1。
    bands: dict[str, float]
    #: 基频的中位数与 10%–90% 范围(Hz)。有声的帧太少(和弦、打击乐、噪声)时是 None。
    pitch_hz: float | None
    pitch_range_hz: list[float] | None
    #: 测得出单一音高的帧占比 —— 低于三成时,上面的音高不要当真。
    voiced_ratio: float


def timbre(spectrum: Spectrum, mono_22k: np.ndarray) -> Timbre:
    power = spectrum.power
    energy = spectrum.frame_energy
    audible = energy > energy.max() * 10 ** (-AUDIBLE_WITHIN_DB / 10) if energy.max() > 0 else energy > 0
    power, energy = power[audible], energy[audible]
    freqs = spectrum.frequencies
    if not len(energy):
        return Timbre(0.0, 0.0, 0.0, {name: 0.0 for name in BANDS}, None, None, 0.0)
    centroid = (power * freqs).sum(axis=1) / energy
    cumulative = np.cumsum(power, axis=1)
    rolloff = freqs[np.argmax(cumulative >= 0.85 * cumulative[:, -1:], axis=1)]
    flatness = np.exp(np.mean(np.log(power + 1e-12), axis=1)) / (power.mean(axis=1) + 1e-12)
    total = float(energy.sum())
    bands = {
        name: round(float(power[:, (freqs >= low) & (freqs < high)].sum()) / total, 3)
        for name, (low, high) in BANDS.items()
    }
    pitch, pitch_range, voiced = _pitch(mono_22k)
    return Timbre(
        brightness_hz=round(float(np.average(centroid, weights=energy)), 1),
        rolloff_hz=round(float(np.median(rolloff)), 1),
        noisiness=round(float(np.median(flatness)), 3),
        bands=bands,
        pitch_hz=pitch,
        pitch_range_hz=pitch_range,
        voiced_ratio=voiced,
    )


def _pitch(mono_22k: np.ndarray) -> tuple[float | None, list[float] | None, float]:
    count = len(mono_22k) // PITCH_FRAME
    if count == 0:
        return None, None, 0.0
    frames = mono_22k[: count * PITCH_FRAME].reshape(count, PITCH_FRAME).astype(np.float64)
    if count > PITCH_MAX_FRAMES:
        frames = frames[np.linspace(0, count - 1, PITCH_MAX_FRAMES).astype(int)]
    loud = frames.std(axis=1)
    frames = frames[loud > loud.max() * 0.05] if loud.max() > 0 else frames[:0]
    if not len(frames):
        return None, None, 0.0
    shortest, longest = int(RATE / PITCH_RANGE[1]), int(RATE / PITCH_RANGE[0])
    spectrum_of = np.fft.rfft(frames, n=2 * PITCH_FRAME, axis=1)
    autocorr = np.fft.irfft(spectrum_of * np.conj(spectrum_of), axis=1)[:, : longest + 2]
    squares = np.cumsum(frames**2, axis=1)
    energy_tail = squares[:, -1:] - np.concatenate([np.zeros((len(frames), 1)), squares[:, : longest + 1]], axis=1)
    difference = autocorr[:, :1] + energy_tail - 2 * autocorr  # d(τ) = r(0) + r_τ(0) − 2 r(τ)
    difference[:, 0] = 0
    taus = np.arange(1, difference.shape[1])
    normalised = np.ones_like(difference)
    normalised[:, 1:] = difference[:, 1:] * taus / np.maximum(np.cumsum(difference[:, 1:], axis=1), 1e-12)
    pitches: list[float] = []
    for row in normalised:
        candidates = np.flatnonzero(row[shortest:longest] < YIN_THRESHOLD)
        if len(candidates):
            tau = shortest + int(candidates[0])
            while tau + 1 < longest and row[tau + 1] < row[tau]:
                tau += 1
            pitches.append(RATE / tau)
    voiced = round(len(pitches) / len(frames), 2)
    if len(pitches) < 5:
        return None, None, voiced
    values = np.array(pitches)
    return (
        round(float(np.median(values)), 1),
        [round(float(np.percentile(values, 10)), 1), round(float(np.percentile(values, 90)), 1)],
        voiced,
    )
