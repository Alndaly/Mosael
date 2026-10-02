"""底轨按整帧接:第 k 帧就是时间线上的第 k 帧,段再多、段长再不在帧格上也不往后漂。

此前每段多长由 concat 自己估:画面按「最后一帧的时刻 × 帧数 /(帧数 − 1)」、声音按采样数,取长的那个。段长
不在帧格上(1.234 秒、变速以后的 0.6667 秒……)时每段多出零点几帧,越往后底轨越晚于上层、字幕和音频轨;
而且估出来多少取决于这一段从哪一帧开始 —— 只渲一截(取帧、分块)时接出来的位置就和整条渲时不一样。

素材每一帧亮度不同,逐段看:时间线上这一段的头一帧、末一帧,是不是素材里该是的那一帧。
"""

from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.core.config import settings
from app.media.render_executor import _segment_frames, execute_render
from app.media.render_plan import build_render_plan

pytestmark = pytest.mark.skipif(shutil.which(settings.ffmpeg) is None, reason="ffmpeg not installed")

W, H, FPS = 64, 36, 30


def _luma(path: Path) -> np.ndarray:
    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True, timeout=60).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W).mean(axis=(1, 2))


def test_段长不在帧格上_底轨也不往后漂(tmp_path: Path) -> None:
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=s={W}x{H}:r={FPS}:d=80",
                    "-vf", "geq=lum='mod(N*7,200)+20':cb=128:cr=128", "-c:v", "libx264", "-preset", "ultrafast",
                    "-crf", "0", "-g", "30", "-pix_fmt", "yuv420p", str(tmp_path / "a.mp4")], check=True, timeout=60)
    #: 20 段,段长 1.234 秒(每段 37.02 帧),其中几段变速 1.5 倍(0.8227 秒 = 24.68 帧)。
    clips, at = [], 0.0
    for i in range(20):
        speed = 1.5 if i % 4 == 3 else 1.0
        clips.append({"id": f"c{i}", "asset_id": "a", "timeline_start": round(at, 6), "src_in": i * 3.0,
                      "src_out": i * 3.0 + 1.234, "speed": speed})
        at += 1.234 / speed
    plan = build_render_plan(sequence_id="s", revision=1, width=W, height=H, fps=FPS, crf=0, encode_preset="ultrafast",
                             clips=clips, assets={"a": {"file_key": "a.mp4"}})
    out = tmp_path / "out.mp4"
    execute_render(plan, lambda key: tmp_path / key, out)

    luma, source = _luma(out), _luma(tmp_path / "a.mp4")
    assert len(luma) == math.ceil(plan.timeline_duration * FPS - 1e-6)
    drift = []
    for clip, (first, count) in zip(clips, _segment_frames(plan)):
        #: 段落在第 first 帧(时间线时刻取最近的帧;正好半帧时两边都对),它不能漂出半帧以外。
        assert abs(first - clip["timeline_start"] * FPS) <= 0.5 + 1e-4
        #: 末一帧:变速的段落在两帧源画面中间时取哪一帧都算对。
        last_at = (clip["src_in"] + (count - 1) / FPS * clip["speed"]) * FPS
        last_ok = min(abs(luma[first + count - 1] - source[k]) for k in {math.floor(last_at), math.ceil(last_at)}) <= 1.5
        if abs(luma[first] - source[round(clip["src_in"] * FPS)]) > 1.5 or not last_ok:
            drift.append(first)
    assert not drift, f"这些段的头一帧不是它自己的头一帧(底轨漂了):{drift}"
