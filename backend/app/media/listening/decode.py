"""把一段声音解成 numpy 数组。测量全从这里开始。

固定解成 44.1 kHz 双声道 float32:削波、真峰值、声道相关性要原采样率附近的样本;单声道的源被 ffmpeg 复制成
两条一模一样的声道(相关性 = 1,`levels` 据此说「单声道」)。频谱类的测量另取一份降到 22.05 kHz 的单声道
(`Pcm.mono_22k`),省一半计算,人耳关心的频段一点不少。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import numpy as np

from app.core.child_process import run_logged
from app.core.config import settings
from app.core.i18n import LocalizedError

RATE = 44_100
#: 一次最多听这么长。再长的(整集配乐、几小时的录音)请按 start / end 分段听 —— 一次全量解码要上 G 内存。
MAX_SECONDS = 600.0


class ListeningError(LocalizedError, RuntimeError):
    """听不了:文件读不出、没有音轨、窗口不对。带文案 key(`listenErr_*`)。"""


@dataclass(frozen=True)
class Pcm:
    #: (帧数, 2) 的 float32,范围 [-1, 1]。
    samples: np.ndarray
    rate: int = RATE

    @property
    def seconds(self) -> float:
        return len(self.samples) / self.rate

    @cached_property
    def mono(self) -> np.ndarray:
        return self.samples.mean(axis=1)

    @cached_property
    def mono_22k(self) -> np.ndarray:
        """两两取平均降一半采样率:先平均就是一道最简单的低通,够频谱测量用。"""
        mono = self.mono[: len(self.mono) // 2 * 2]
        return mono.reshape(-1, 2).mean(axis=1)


def decode(path: Path, *, start: float = 0.0, end: float | None = None) -> Pcm:
    """解出 `path` 里 [start, end) 那一段的声音。视频取它的音轨。"""
    if start < 0 or (end is not None and end <= start):
        raise ListeningError("listenErr_window")
    length = min(MAX_SECONDS, (end - start) if end is not None else MAX_SECONDS)
    #: 单声道按单声道解,再在这里复制成两条:交给 ffmpeg 升成立体声,它按「中置声道」各压 3 dB 分到左右,
    #: 峰值、削波、响度全会量轻。多声道(5.1)照常混成立体声。
    channels = 1 if _channels(path) == 1 else 2
    result = run_logged(
        [settings.ffmpeg, "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(path),
         "-vn", "-ac", str(channels), "-ar", str(RATE), "-f", "f32le", "-"],
        capture_output=True, timeout=300, what="解码音频", level=logging.DEBUG,
    )
    if result.returncode != 0:
        raise ListeningError("listenErr_decode")
    samples = np.frombuffer(result.stdout, dtype="<f4").reshape(-1, channels)
    if channels == 1:
        samples = np.repeat(samples, 2, axis=1)
    if len(samples) < RATE // 10:
        raise ListeningError("listenErr_noAudio")
    return Pcm(samples=samples)


def _channels(path: Path) -> int | None:
    """第一条音轨的声道数;没有音轨或探不出时是 None(交给解码那一步去报错)。"""
    result = run_logged(
        [settings.ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=20, what="探测声道数", level=logging.DEBUG,
    )
    value = result.stdout.strip().splitlines()[0] if result.returncode == 0 and result.stdout.strip() else ""
    return int(value) if value.isdigit() else None
