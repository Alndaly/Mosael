"""底轨的声音一直响到片尾 —— 上面压着一条和它同时收尾的音乐也一样。

配乐铺满全片是最常见的样子:音乐和底轨同时收尾。ffmpeg 7.0 之前的 amix 在第一路(底轨)结束的那一刻就把它关掉,
它 FIFO 里还在等音乐那一路一起混的采样全部扔掉 —— Ubuntu 24.04 的 ffmpeg 6.1 上,成片最后约半秒只剩音乐。
这里拿真 ffmpeg 渲一条,量最后那一截里底轨那个频率还在不在(修法见 render_executor 里 amix 前面的注释)。
"""

from __future__ import annotations

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


def _amplitude(samples: np.ndarray, freq: float) -> float:
    """samples 里 freq 这个频率的幅度(整数个周期的窗,投影出来就是幅度)。"""
    t = np.arange(len(samples)) / RATE
    return float(2 * abs(np.dot(samples, np.exp(-2j * np.pi * freq * t))) / len(samples))


def test_音乐和底轨同时收尾_底轨最后那一截的声音还在(tmp_path: Path) -> None:
    #: 底轨的声音用 PCM(没有 AAC 的起始延迟);底轨 440 Hz,音乐 660 Hz,两个频率分得开。
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", "color=black:s=32x32:r=30:d=4",
                    "-f", "lavfi", "-i", f"sine=f=440:r={RATE}:d=4", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", "-shortest", str(tmp_path / "base.mov")],
                   check=True, timeout=60)
    subprocess.run([settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"sine=f=660:r={RATE}:d=3",
                    str(tmp_path / "music.wav")], check=True, timeout=60)
    #: 底轨从素材第 1 秒剪起(剪辑里几乎每一段都是这样)。6.1 上实测:从素材中间剪起的段丢了最后半秒,
    #: 从素材 0 秒开始的段碰巧不丢 —— 丢不丢看底轨那一路比音乐那一路先跑出去多远。
    plan = build_render_plan(
        sequence_id="s", revision=1, width=32, height=32, fps=30, crf=0, encode_preset="ultrafast",
        clips=[{"id": "b", "asset_id": "b", "timeline_start": 0, "src_in": 1.0, "src_out": 4.0}],
        audio_clips=[{"id": "m", "asset_id": "m", "timeline_start": 0.5, "src_in": 0, "src_out": 2.5}],
        assets={"b": {"file_key": "base.mov"}, "m": {"file_key": "music.wav"}},
    )
    out = tmp_path / "out.mp4"
    execute_render(plan, lambda key: tmp_path / key, out)

    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(out), "-map", "0:a", "-ac", "1", "-f", "f32le", "-"],
                         capture_output=True, check=True, timeout=60).stdout
    sound = np.frombuffer(raw, np.float32)
    #: 0.4 秒的窗:440 Hz 和 660 Hz 都是整数个周期,互不串。
    middle = _amplitude(sound[round(1.0 * RATE):round(1.4 * RATE)], 440)
    tail = _amplitude(sound[round(2.5 * RATE):round(2.9 * RATE)], 440)
    assert middle > 0.01, "底轨的声音没进成片"
    assert tail > 0.9 * middle, f"片尾那一截底轨的声音没了:中段 {middle:.4f},片尾 {tail:.4f}"
