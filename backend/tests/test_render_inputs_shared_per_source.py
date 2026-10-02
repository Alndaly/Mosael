"""同一素材在基底轨上接着往后用的几段,共用一路输入(split / asplit 分给各段)。

此前一段一路输入:一条口播剪成 150 段就是 150 个解码器(1080p 每个约 25 MB)、150 次快进、150 个 `-i`。
审查那条 270 秒的时间线,输入 161 → 12,峰值内存 4.7 GB → 2.7 GB。

顺带好了的一件事:每段各自 `-ss` 快进时,快进点落在关键帧上(相机、录屏的素材很常见),**剪辑点开头
几十毫秒的声音和源对不上**(实测误差有信号的四成到七成,听起来是一声「咔」)。共用一路输入的那些
剪辑点是连续解码,声音和源一样。

真 ffmpeg 渲:逐段看画面是不是源里那一帧、声音是不是源里那一段。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from app.core.config import settings
from app.media.render_executor import build_ffmpeg_command, execute_render
from app.media.render_plan import build_render_plan

pytestmark = pytest.mark.skipif(shutil.which(settings.ffmpeg) is None, reason="ffmpeg not installed")

W, H, FPS, RATE = 64, 36, 30, 48000


def _source(path: Path, seconds: float) -> None:
    """每一帧亮度不同(帧号 × 7)、声音是 440 Hz 正弦:错一帧、错一个剪辑点都看得出来。
    ultrafast:画面帧大、音视频交错得疏(相机和录屏的素材就是这样),快进落在关键帧上时声音头上缺一截。"""
    subprocess.run(
        [settings.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=s={W}x{H}:r={FPS}:d={seconds}",
         "-f", "lavfi", "-i", f"sine=f=440:r={RATE}:d={seconds}",
         "-vf", "geq=lum='mod(N*7,200)+20':cb=128:cr=128", "-shortest",
         "-c:v", "libx264", "-preset", "ultrafast", "-g", "60", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
         str(path)],
        check=True, timeout=60,
    )


def _luma(path: Path) -> np.ndarray:
    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(path), "-f", "rawvideo", "-pix_fmt", "gray", "-"],
                         capture_output=True, check=True, timeout=60).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, H, W).mean(axis=(1, 2))


def _pcm(path: Path) -> np.ndarray:
    raw = subprocess.run([settings.ffmpeg, "-v", "error", "-i", str(path), "-map", "0:a", "-ac", "1", "-ar", str(RATE),
                          "-f", "f32le", "-"], capture_output=True, check=True, timeout=60).stdout
    return np.frombuffer(raw, np.float32)


#: 一条源剪成 9 段往后走(跳剪,每段 1.8 秒、跳过 0.2 秒),中间插一段倒回去用的:(时间线起点, 源入点, 源出点)。
#: 入点都落在关键帧上(-g 60,两秒一个)—— 各段各自快进时,声音出错的正是这种剪辑点。
_CUTS = [(i * 1.8, i * 2.0, i * 2.0 + 1.8) for i in range(5)] + [(9.0, 2.0, 3.8)] + [
    (10.8 + i * 1.8, 10.0 + i * 2.0, 11.8 + i * 2.0) for i in range(4)
]


def _plan(**extra):
    return build_render_plan(
        sequence_id="s", revision=1, width=W, height=H, fps=FPS, crf=0, encode_preset="ultrafast",
        clips=[{"id": f"c{i}", "asset_id": "a", "timeline_start": start, "src_in": src_in, "src_out": src_out}
               for i, (start, src_in, src_out) in enumerate(_CUTS)],
        assets={"a": {"file_key": "a.mp4"}}, **extra,
    )


def test_接着往后剪的几段共用一路输入_倒回去用的另开一路(tmp_path: Path) -> None:
    _source(tmp_path / "a.mp4", 20)
    command = build_ffmpeg_command(_plan(), lambda key: tmp_path / key, tmp_path / "o.mp4")
    graph = command[command.index("-filter_complex") + 1]
    #: 前 5 段一路;倒回去的那段另开一路;它后面那 4 段接回第一路(第一路的出点在 9.8,它们从 10.0 起)。
    assert command.count("-i") == 2, command
    assert "split=9" in graph and "asplit=9" in graph, graph


def test_共用输入渲出来_每一帧是源里那一帧_剪辑点上的声音和源一样(tmp_path: Path) -> None:
    _source(tmp_path / "a.mp4", 20)
    plan = _plan()
    out = tmp_path / "out.mp4"
    execute_render(plan, lambda key: tmp_path / key, out)

    luma, source_luma = _luma(out), _luma(tmp_path / "a.mp4")
    assert len(luma) == round(plan.timeline_duration * FPS), "成片时长变了"
    for start, src_in, src_out in _CUTS:
        for offset in (0, 11, round((src_out - src_in) * FPS) - 1):  # 每段的头一帧、中间、末一帧
            k = round(start * FPS) + offset
            expected = source_luma[round(src_in * FPS) + offset]
            assert abs(luma[k] - expected) < 1.5, f"时间线第 {k} 帧不是源里那一帧({luma[k]:.1f} ≠ {expected:.1f})"

    sound, source_sound = _pcm(out), _pcm(tmp_path / "a.mp4")
    signal = float(np.sqrt(np.mean(source_sound ** 2)))
    window = int(0.04 * RATE)
    #: 共用输入里接着往后的那几段(第 0 段从头开始、第 5 段倒回去另开一路,都要自己快进,不在此列)。
    for start, src_in, _src_out in _CUTS[1:5] + _CUTS[6:]:
        at, src_at = round(start * RATE), round(src_in * RATE)
        error = float(np.sqrt(np.mean((sound[at:at + window] - source_sound[src_at:src_at + window]) ** 2)))
        assert error < signal * 0.05, f"{start}s 剪辑点开头 40 毫秒的声音和源对不上(误差 {error:.4f},信号 {signal:.4f})"
