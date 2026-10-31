"""音频变速的 atempo 滤镜。成片渲染(render_executor)、对口型配音(dub_lipsync)和合成之后的变速
(`stretch_in_place`,给没有语速参数的配音引擎用)共用这一份。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from app.core.child_process import run_logged
from app.core.config import settings
from app.core.i18n import LocalizedError

#: 合成之后变速的范围。atempo 本身收得更宽(串几级),但离原速越远,变速的痕迹越明显;
#: 界面的语速档也在这个范围内(SpeedPicker)。
STRETCH_MIN = 0.5
STRETCH_MAX = 2.0


class TempoError(LocalizedError, RuntimeError):
    """变速没做成。带文案 key(`tempoErr_*`)。"""


def atempo_filters(speed: float) -> str:
    """把 `speed` 倍速拆成几级 atempo —— ffmpeg 的一级 atempo 只收 0.5–2 倍,更快或更慢要串起来。

    返回的是**可以直接接在滤镜链中间的一段**,自带尾随逗号(`atempo=2.0,atempo=1.5,`);原速返回空串,
    调用处不必为「要不要变速」另写分支。
    """
    if speed == 1.0:
        return ""
    parts: list[str] = []
    remaining = speed
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining}")
    return ",".join(parts) + ","


def stretch_in_place(path: Path, speed: float) -> None:
    """把一段音频就地变速到 `speed` 倍,音高不变(atempo)。原速什么都不做。

    给**没有语速参数的配音引擎**用(`speed_control == "stretch"`:fish、Qwen3-TTS、百炼 qwen-tts):
    它们按原速念,宿主在这里补上语速 —— 于是语速对每个引擎都可调,不必为某一家另写一套。
    输出沿用原文件的容器与后缀(wav 进 wav 出、mp3 进 mp3 出),写临时文件再原子替换,失败时原文件不动。
    """
    if speed == 1.0:
        return
    if not STRETCH_MIN <= speed <= STRETCH_MAX:
        raise TempoError("tempoErr_outOfRange", speed=speed, low=STRETCH_MIN, high=STRETCH_MAX)
    staged = path.with_name(f".{path.stem}.stretched{path.suffix}")
    filters = atempo_filters(speed).rstrip(",")
    try:
        run_logged(
            [settings.ffmpeg, "-y", "-v", "error", "-i", str(path), "-filter:a", filters, str(staged)],
            check=True, capture_output=True, timeout=600, what="合成之后变速",
        )
    except subprocess.SubprocessError as exc:
        staged.unlink(missing_ok=True)
        raise TempoError("tempoErr_failed") from exc
    if not staged.is_file() or staged.stat().st_size == 0:
        staged.unlink(missing_ok=True)
        raise TempoError("tempoErr_failed")
    os.replace(staged, path)
