from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from app.core.child_process import run_logged
from app.core.config import settings

"""
Waveform cache (plan §8): peak buckets computed once at import time and
stored beside the asset, served as JSON for timeline rendering.
"""

WAVEFORM_NAME = "waveform.json"
SAMPLE_RATE = 8000
BUCKETS = 1000


def waveform_path(asset_directory: Path) -> Path:
    return asset_directory / WAVEFORM_NAME


def generate_waveform(source: Path, kind: str, asset_directory: Path) -> Path | None:
    """Best-effort mono peak extraction; import must never fail because of it."""
    if kind not in ("audio", "video"):
        return None
    try:
        proc = run_logged(
            [
                settings.ffmpeg, "-v", "error",
                "-i", str(source),
                "-map", "0:a:0",
                "-ac", "1",
                "-ar", str(SAMPLE_RATE),
                "-f", "s16le",
                "-",
            ],
            check=True,
            capture_output=True,
            timeout=60, what="波形生成")
    except Exception:
        return None
    pcm = proc.stdout
    if len(pcm) < 2:
        return None

    peaks = compute_peaks(pcm, BUCKETS)
    duration = (len(pcm) // 2) / SAMPLE_RATE
    target = waveform_path(asset_directory)
    target.write_text(
        json.dumps({"version": 1, "duration": round(duration, 3), "peaks": peaks}), encoding="utf-8"
    )
    return target


def compute_peaks(pcm_s16le: bytes, buckets: int) -> list[float]:
    """Max-abs peak per bucket, normalized to [0, 1] with 2 decimals.

    向量化算(numpy)。此前逐样本一个 Python 循环:10 分钟的音频 1.8 秒、一小时约 11 秒,而这段跑在导入请求里、启动对账也走它
    (MED-10)。桶的边界和取值和原来逐字一样:第 i 桶是 `[int(i·每桶), int((i+1)·每桶))` 个样本,取绝对值最大的那个
    (-32768 记 32768),除以 32768 保留两位。"""
    total_samples = len(pcm_s16le) // 2
    if total_samples == 0:
        return []
    bucket_count = min(buckets, total_samples)
    samples_per_bucket = total_samples / bucket_count
    samples = np.frombuffer(pcm_s16le, dtype="<i2", count=total_samples)
    #: int32 再取绝对值:int16 的 -32768 取绝对值会溢出回 -32768。
    magnitudes = np.abs(samples.astype(np.int32))
    #: 每桶至少一个样本(桶数不超过样本数),起点严格递增,reduceat 正好按桶取最大值。最后一桶的终点照原来的算法取
    #: `int(桶数·每桶)` —— 浮点误差下它偶尔比样本数少一,原来那一版就不看最后那个样本;照旧,画出来的波形一点不变。
    starts = (np.arange(bucket_count) * samples_per_bucket).astype(np.int64)
    end = int(bucket_count * samples_per_bucket)
    maxima = np.maximum.reduceat(magnitudes[:end], starts)
    return [round(int(peak) / 32768, 2) for peak in maxima]
