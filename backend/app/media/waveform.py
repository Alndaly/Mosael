from __future__ import annotations

import json
import subprocess
from pathlib import Path
from app.core.child_process import run_logged

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
                "ffmpeg", "-v", "error",
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
    target.write_text(json.dumps({"version": 1, "duration": round(duration, 3), "peaks": peaks}))
    return target


def compute_peaks(pcm_s16le: bytes, buckets: int) -> list[float]:
    """Max-abs peak per bucket, normalized to [0, 1] with 2 decimals."""
    total_samples = len(pcm_s16le) // 2
    if total_samples == 0:
        return []
    bucket_count = min(buckets, total_samples)
    samples_per_bucket = total_samples / bucket_count
    peaks: list[float] = []
    view = memoryview(pcm_s16le)
    for index in range(bucket_count):
        start = int(index * samples_per_bucket) * 2
        end = int((index + 1) * samples_per_bucket) * 2
        chunk = view[start:end]
        peak = 0
        for offset in range(0, len(chunk) - 1, 2):
            value = int.from_bytes(chunk[offset : offset + 2], "little", signed=True)
            magnitude = -value if value < 0 else value
            if magnitude > peak:
                peak = magnitude
        peaks.append(round(peak / 32768, 2))
    return peaks
