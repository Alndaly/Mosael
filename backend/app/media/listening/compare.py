"""两段以上一起听:音色差在哪。

只交数,不下结论:哪一个「更适合当旁白」是模型结合上下文判断的事。每一对给出明亮度之比、音高差多少半音、
三段能量的占比差、响度差和一个综合的音色距离(0 相同,越大越不像)。
"""

from __future__ import annotations

import math
from itertools import combinations
from typing import Any


def compare(reports: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    for a, b in combinations(reports, 2):
        ta, tb = a["timbre"], b["timbre"]
        pitch = (
            round(12 * math.log2(tb["pitch_hz"] / ta["pitch_hz"]), 1)
            if ta["pitch_hz"] and tb["pitch_hz"] and min(ta["voiced_ratio"], tb["voiced_ratio"]) >= 0.3
            else None
        )
        bands = {name: round((tb["bands"][name] - ta["bands"][name]) * 100, 1) for name in ta["bands"]}
        brightness = round(tb["brightness_hz"] / ta["brightness_hz"], 2) if ta["brightness_hz"] else None
        la, lb = a["loudness"]["integrated"], b["loudness"]["integrated"]
        pairs.append({
            "a": a["asset_id"],
            "b": b["asset_id"],
            #: b 的明亮度是 a 的几倍。
            "brightness_ratio": brightness,
            #: b 比 a 高多少个半音(正数更高);两段里有一段测不出单一音高时为 None。
            "pitch_semitones": pitch,
            #: b 减 a 的三段能量占比(百分点)。
            "band_shift_points": bands,
            "loudness_diff_lu": round(lb - la, 1) if la is not None and lb is not None else None,
            "noisiness_diff": round(tb["noisiness"] - ta["noisiness"], 3),
            "timbre_distance": _distance(ta, tb, pitch),
        })
    return pairs


def _distance(ta: dict[str, Any], tb: dict[str, Any], pitch: float | None) -> float:
    """明亮度(按倍数,一倍算 1)、三段占比(每 25 个百分点算 1)、平坦度(每 0.1 算 1)、音高(一个八度算 1)。"""
    parts = [
        math.log2(max(tb["brightness_hz"], 1.0) / max(ta["brightness_hz"], 1.0)),
        *((tb["bands"][name] - ta["bands"][name]) / 0.25 for name in ta["bands"]),
        (tb["noisiness"] - ta["noisiness"]) / 0.1,
        (pitch or 0.0) / 12,
    ]
    return round(math.sqrt(sum(part * part for part in parts)), 2)
