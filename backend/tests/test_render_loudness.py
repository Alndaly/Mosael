"""混音之后的总线:**限幅总是有**,响度标准化可选。

amix 是直接相加(normalize=0),增益关键帧又能拉到 4 倍:几条声音叠在一起采样轻易超过 ±1,编码时被
硬削成方波。审查实测一段三轨叠加有 9% 的采样贴在 0 dBFS 上。

真 ffmpeg 导出,从成片里读采样、用 ebur128 量响度。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.core.config import settings
from app.media.render_executor import execute_render
from app.media.render_plan import build_render_plan

pytestmark = pytest.mark.skipif(shutil.which(settings.ffmpeg) is None, reason="ffmpeg not installed")

RATE = 48000


def _tone(path: Path, freq: int, amplitude: float, seconds: float, *, video: bool = False) -> None:
    sources = ["-f", "lavfi", "-i", f"color=black:s=64x36:r=10:d={seconds}"] if video else []
    # sine 自己的幅度是 1/8:乘 8 回到 1 再乘想要的幅度。
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", *sources, "-f", "lavfi",
                    "-i", f"sine=f={freq}:d={seconds}:r={RATE},volume={8 * amplitude}",
                    *(["-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-shortest"] if video else []), str(path)],
                   check=True, timeout=60)


def _samples(path: Path) -> np.ndarray:
    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(path), "-vn", "-ar", str(RATE), "-f", "f32le", "-"],
                         capture_output=True, check=True, timeout=60).stdout
    return np.frombuffer(raw, np.float32)


def _loudness(path: Path) -> tuple[float, float]:
    """(整体响度 LUFS, 真峰值 dBTP)。"""
    log = subprocess.run([settings.ffmpeg, "-hide_banner", "-nostats", "-i", str(path), "-vn", "-af", "ebur128=peak=true",
                          "-f", "null", "-"], capture_output=True, text=True, timeout=60).stderr
    summary = log[log.rindex("Summary:"):]
    integrated = float(re.search(r"I:\s+(-?[\d.]+) LUFS", summary).group(1))
    peak = float(re.search(r"Peak:\s+(-?[\d.]+) dBFS", summary).group(1))
    return integrated, peak


def _three_loud_tracks(tmp_path: Path, *, loudness_normalize: bool = False):
    _tone(tmp_path / "base.mov", 220, 0.6, 6, video=True)
    _tone(tmp_path / "music.wav", 330, 0.5, 6)
    _tone(tmp_path / "voice.wav", 440, 0.5, 6)
    return build_render_plan(
        sequence_id="s", revision=1, width=64, height=36, fps=10,
        clips=[{"id": "base", "asset_id": "base", "timeline_start": 0, "src_in": 0, "src_out": 6, "has_audio": True}],
        assets={"base": {"file_key": "base.mov"}, "music": {"file_key": "music.wav"}, "voice": {"file_key": "voice.wav"}},
        audio_clips=[
            {"id": "m", "asset_id": "music", "timeline_start": 0, "src_in": 0, "src_out": 6, "gain": 1.0},
            # 增益关键帧从 1 拉到 4 —— 允许的最大值
            {"id": "v", "asset_id": "voice", "timeline_start": 0, "src_in": 0, "src_out": 6, "gain": 1.0,
             "effects": {"gain_keyframes": [{"t": 0, "gain": 1}, {"t": 1, "gain": 4}]}},
        ],
        loudness_normalize=loudness_normalize,
    )


def test_三轨叠加加上_4_倍增益_成片不削波(tmp_path) -> None:
    out = tmp_path / "out.mp4"
    execute_render(_three_loud_tracks(tmp_path), lambda key: tmp_path / key, out)
    samples = np.abs(_samples(out))
    assert samples.max() < 0.97, f"峰值 {samples.max():.3f}:限幅没起作用"
    assert (samples >= 0.99).mean() == 0, "有采样贴着 0 dBFS —— 被硬削了"
    # 限幅不是把整条压小:叠加起来本来就响,成片仍然接近天花板。
    assert samples.max() > 0.8


def test_限幅不改动本来就没超的声音(tmp_path) -> None:
    _tone(tmp_path / "quiet.mov", 440, 0.25, 4, video=True)
    plan = build_render_plan(
        sequence_id="s", revision=1, width=64, height=36, fps=10,
        clips=[{"id": "base", "asset_id": "quiet", "timeline_start": 0, "src_in": 0, "src_out": 4, "has_audio": True}],
        assets={"quiet": {"file_key": "quiet.mov"}},
    )
    out = tmp_path / "out.mp4"
    execute_render(plan, lambda key: tmp_path / key, out)
    middle = _samples(out)[RATE:3 * RATE]  # 立体声交错;只看幅度
    assert np.abs(middle).max() == pytest.approx(0.25 / np.sqrt(2), rel=0.08), "没超的声音被限幅器改了音量"


def test_响度标准化_打开后约_负14_LUFS_关着不动(tmp_path) -> None:
    _tone(tmp_path / "soft.mov", 440, 0.03, 8, video=True)
    plan = dict(sequence_id="s", revision=1, width=64, height=36, fps=10,
                clips=[{"id": "b", "asset_id": "soft", "timeline_start": 0, "src_in": 0, "src_out": 8, "has_audio": True}],
                assets={"soft": {"file_key": "soft.mov"}})
    off, on = tmp_path / "off.mp4", tmp_path / "on.mp4"
    execute_render(build_render_plan(**plan), lambda key: tmp_path / key, off)
    execute_render(build_render_plan(**plan, loudness_normalize=True), lambda key: tmp_path / key, on)
    quiet, _ = _loudness(off)
    loud, peak = _loudness(on)
    assert quiet < -25, f"没打开时不该动响度:{quiet}"
    assert loud == pytest.approx(-14, abs=1.5)
    assert peak <= -0.5
