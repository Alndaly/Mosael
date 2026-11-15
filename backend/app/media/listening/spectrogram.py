"""一张频谱图:横轴时间、纵轴频率(对数)、亮度是能量,带刻度和图例。

给收图的模型自己看(断档是竖着的黑带、爆音是贯穿上下的亮线、鼓点是均匀的竖线、旋律是横纹),
也给对话里那张卡片给人看。ffmpeg 的 showspectrumpic 画,不另引绘图库。
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.child_process import run_logged
from app.core.config import settings
from app.media.listening.decode import MAX_SECONDS, ListeningError

SIZE = "1200x360"


def spectrogram_png(path: Path, *, start: float = 0.0, end: float | None = None) -> bytes:
    length = min(MAX_SECONDS, (end - start) if end is not None else MAX_SECONDS)
    result = run_logged(
        [settings.ffmpeg, "-v", "error", "-ss", f"{start:.3f}", "-t", f"{length:.3f}", "-i", str(path), "-vn",
         "-lavfi", f"showspectrumpic=s={SIZE}:legend=1:scale=log:fscale=log", "-frames:v", "1",
         "-f", "image2", "-c:v", "png", "-"],
        capture_output=True, timeout=120, what="画频谱图", level=logging.DEBUG,
    )
    if result.returncode != 0 or not result.stdout:
        raise ListeningError("listenErr_decode")
    return result.stdout
