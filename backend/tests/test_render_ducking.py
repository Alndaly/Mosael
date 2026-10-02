"""闪避:一集译配一两百句配音,导出照样过;压下去 / 抬回来有 30 ms 的斜坡。

此前每个闪避窗口在 volume 的 enable 表达式里拼一段 `between(t,a,b)`,窗口一多表达式超过 ffmpeg 的解析上限,
导出直接失败(审查实测 100 段左右开始挂)。窗口边上也是一刀切,音乐瞬间掉 10 dB。
现在是一条预先算好的增益包络(1 kHz 写进中转目录),和声音逐采样相乘。

真 ffmpeg 导出 150 段配音的时间线,从成片里量被压的那条声音。配音本身用几乎听不见的增益,
量到的就只剩被压的那一条。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.core.config import settings
from app.media.render_executor import DUCK_GAIN, DUCK_RAMP, execute_render
from app.media.render_plan import build_render_plan

pytestmark = pytest.mark.skipif(shutil.which(settings.ffmpeg) is None, reason="ffmpeg not installed")

RATE = 48000
LINES, EVERY, LONG = 150, 0.4, 0.2  # 150 句,每 0.4 秒一句,每句 0.2 秒
SECONDS = LINES * EVERY + 1


def _tone(path: Path, seconds: float, *, video: bool) -> None:
    sources = (["-f", "lavfi", "-i", f"color=black:s=64x36:r=10:d={seconds}"] if video else [])
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", *sources, "-f", "lavfi",
                    "-i", f"sine=f=440:d={seconds}:r={RATE}", *(["-pix_fmt", "yuv420p", "-shortest"] if video else []),
                    str(path)], check=True, timeout=60)


def _levels(path: Path) -> np.ndarray:
    """每 5 ms 一格的 RMS。"""
    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(path), "-vn", "-ac", "1", "-ar", str(RATE),
                          "-f", "f32le", "-"], capture_output=True, check=True, timeout=60).stdout
    samples = np.frombuffer(raw, np.float32)
    cell = RATE // 200
    return np.sqrt((samples[: len(samples) // cell * cell].reshape(-1, cell) ** 2).mean(axis=1))


def _at(levels: np.ndarray, seconds: float) -> float:
    return float(levels[int(round(seconds * 200))])


def _lines() -> list[dict]:
    return [{"id": f"d{n}", "asset_id": "line", "timeline_start": round(1 + n * EVERY, 3), "src_in": 0,
             "src_out": LONG, "gain": 0.001} for n in range(LINES)]


def _check(levels: np.ndarray) -> None:
    full = _at(levels, 0.5)  # 第一句之前
    assert full > 0.01
    for n in (0, LINES // 2, LINES - 1):
        start = 1 + n * EVERY
        assert _at(levels, start + LONG / 2) / full == pytest.approx(DUCK_GAIN, abs=0.06), f"第 {n} 句没压下去"
        assert _at(levels, start + LONG + 0.1) / full == pytest.approx(1.0, abs=0.08), f"第 {n} 句之后没抬回来"
        # 斜坡:开口前 DUCK_RAMP 秒开始往下走,开口那一刻到底 —— 中间那一格在两者之间,不是一刀切。
        middle = _at(levels, start - DUCK_RAMP / 2 - 0.0025) / full
        assert DUCK_GAIN + 0.1 < middle < 0.95, f"第 {n} 句的压低没有斜坡:{middle:.2f}"


def test_基底轨标了闪避_150_段配音照样导得出来(tmp_path) -> None:
    _tone(tmp_path / "base.mp4", SECONDS, video=True)
    _tone(tmp_path / "line.wav", LONG, video=False)
    plan = build_render_plan(
        sequence_id="s", revision=1, width=64, height=36, fps=10,
        clips=[{"id": "base", "asset_id": "base", "timeline_start": 0, "src_in": 0, "src_out": SECONDS, "has_audio": True}],
        assets={"base": {"file_key": "base.mp4"}, "line": {"file_key": "line.wav"}},
        audio_clips=_lines(), duck_base_audio=True,
    )
    assert len(plan.base_audio_duck_windows) == LINES
    out = tmp_path / "out.mp4"
    execute_render(plan, lambda key: tmp_path / key, out)
    _check(_levels(out))


def test_音乐轨标了闪避_150_段配音照样导得出来(tmp_path) -> None:
    _tone(tmp_path / "black.mp4", SECONDS, video=True)
    _tone(tmp_path / "music.wav", SECONDS, video=False)
    _tone(tmp_path / "line.wav", LONG, video=False)
    plan = build_render_plan(
        sequence_id="s", revision=1, width=64, height=36, fps=10,
        clips=[{"id": "base", "asset_id": "black", "timeline_start": 0, "src_in": 0, "src_out": SECONDS}],
        assets={"black": {"file_key": "black.mp4"}, "music": {"file_key": "music.wav"}, "line": {"file_key": "line.wav"}},
        audio_clips=[{"id": "m", "asset_id": "music", "timeline_start": 0, "src_in": 0, "src_out": SECONDS,
                      "gain": 1.0, "duck": True}, *_lines()],
        mute_base_audio=True,
    )
    assert len(plan.audio_overlays[0].duck_windows) == LINES
    out = tmp_path / "out.mp4"
    execute_render(plan, lambda key: tmp_path / key, out)
    _check(_levels(out))
