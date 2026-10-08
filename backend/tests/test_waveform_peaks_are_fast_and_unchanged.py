"""波形峰值向量化之后:结果和原来逐样本那一版逐字一样,一小时的音频不再要十几秒(MED-10)。

此前 `compute_peaks` 每个样本一次 Python 循环:10 分钟 1.8 秒、一小时约 11 秒,而它跑在导入请求里,启动对账也走它。
"""

from __future__ import annotations

import random
import struct
import time

import pytest

from app.media.waveform import SAMPLE_RATE, compute_peaks


def _reference(pcm: bytes, buckets: int) -> list[float]:
    """原来那一版(逐样本循环),拿来对答案。"""
    total = len(pcm) // 2
    if total == 0:
        return []
    count = min(buckets, total)
    per = total / count
    view = memoryview(pcm)
    peaks: list[float] = []
    for index in range(count):
        chunk = view[int(index * per) * 2:int((index + 1) * per) * 2]
        peak = 0
        for offset in range(0, len(chunk) - 1, 2):
            value = int.from_bytes(chunk[offset:offset + 2], "little", signed=True)
            peak = max(peak, -value if value < 0 else value)
        peaks.append(round(peak / 32768, 2))
    return peaks


def _pcm(samples: list[int]) -> bytes:
    return struct.pack(f"<{len(samples)}h", *samples)


@pytest.mark.parametrize("length", [0, 1, 7, 999, 1000, 1001, 4321, 20000])
def test_和原来逐样本那一版逐字一样(length: int) -> None:
    rng = random.Random(length)
    samples = [rng.randint(-32768, 32767) for _ in range(length)]
    pcm = _pcm(samples)
    assert compute_peaks(pcm, 1000) == _reference(pcm, 1000)
    assert compute_peaks(pcm + b"\x01", 1000) == _reference(pcm + b"\x01", 1000), "奇数字节的尾巴照旧不算"


def test_最小值不溢出() -> None:
    assert compute_peaks(_pcm([-32768, 0, 5]), 1) == [1.0]


def test_一小时的音频一秒内算完() -> None:
    pcm = (_pcm([1200, -3000, 32767, -32768]) * (SAMPLE_RATE // 4)) * 3600  # 一小时,57.6 MB
    started = time.perf_counter()
    peaks = compute_peaks(pcm, 1000)
    elapsed = time.perf_counter() - started
    assert len(peaks) == 1000 and peaks[0] == 1.0
    assert elapsed < 1.5, f"一小时音频算了 {elapsed:.1f} 秒"
