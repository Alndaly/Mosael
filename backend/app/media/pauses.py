"""把一段话里过长的停顿压到一个上限:找出停顿(`find_pauses`)、算出留下哪几截(`kept_spans`)、拼回一段(`join_spans`)。

**为什么要压。** 视频模型拿一段音频驱动口型时,长静音会诱使它换镜头:H3 数字人的硬切都落在静音里(一处 1.2 秒的
句间停顿、末段补齐的那截静音;配音和画面一样长、没有长静音的续写段一段都没切,见 ADR 0092)。切不切还看种子,
所以这是降低风险,不是开关。停顿压到一个上限,话的内容、语速一点不动,只是句与句之间不再空那么久。

**只剪停顿中间那一截。** 一处停顿压到上限时,前后各留一半:话说完之后的那点尾音、下一句起头前的那口气都还在,
接缝落在静音正中,听不出剪过。片头片尾的静音同样只留上限那么长。

这一层不碰数据库,只认文件路径;登记成素材是 domain/assets/pauses 的事。
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.child_process import run_logged
from app.core.config import settings
from app.core.i18n import LocalizedError

#: 比这更轻的声音算静音。配音引擎的底噪在 -60 dB 上下,换气声在 -40 dB 左右;-35 dB 把换气也算进静音,
#: 句间停顿就是「从上一句的最后一个字到下一句的第一个字」,和人耳听到的那段空白一致。
SILENCE_FLOOR_DB = -35.0
#: 默认的停顿上限(秒)。实测前几段停顿在 0.4–1.06 秒之间都没切;0.6 秒仍听得出是句号,而离出事的 1.2 秒有一倍余量。
DEFAULT_MAX_PAUSE = 0.6
#: 上限的取值范围:再短就像把两句话粘在一起,再长就失去了压的意义。
MAX_PAUSE_RANGE = (0.2, 3.0)

_SILENCE_START = re.compile(r"silence_start:\s*(-?[\d.]+)")
_SILENCE_END = re.compile(r"silence_end:\s*(-?[\d.]+)")


class PauseError(LocalizedError, RuntimeError):
    """压停顿没做成。带文案 key(`pauseErr_*`)。"""


@dataclass(frozen=True)
class Span:
    """一截时间:从 `start` 到 `end`(秒)。"""

    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


def parse_silences(ffmpeg_log: str, *, duration: float) -> list[Span]:
    """读 ffmpeg `silencedetect` 的输出。最后一处静音一直到片尾时只有起点,没有终点 —— 终点就是片尾。"""
    silences: list[Span] = []
    start: float | None = None
    for line in ffmpeg_log.splitlines():
        if (found := _SILENCE_START.search(line)) is not None:
            start = max(0.0, float(found.group(1)))
        elif (found := _SILENCE_END.search(line)) is not None and start is not None:
            silences.append(Span(start, min(duration, float(found.group(1)))))
            start = None
    if start is not None and start < duration:
        silences.append(Span(start, duration))
    return silences


def find_pauses(path: Path, *, duration: float, longer_than: float) -> list[Span]:
    """这段音频里长过 `longer_than` 秒的静音(见 `SILENCE_FLOOR_DB`)。"""
    try:
        done = run_logged(
            [settings.ffmpeg, "-hide_banner", "-nostats", "-i", str(path),
             "-af", f"silencedetect=noise={SILENCE_FLOOR_DB}dB:duration={longer_than}", "-f", "null", "-"],
            check=True, capture_output=True, text=True, timeout=600, what="找停顿",
        )
    except subprocess.SubprocessError as exc:
        raise PauseError("pauseErr_detectFailed") from exc
    return parse_silences(done.stderr or "", duration=duration)


def kept_spans(duration: float, pauses: list[Span], max_pause: float) -> list[Span]:
    """压完之后留下的那几截。每处长过 `max_pause` 的停顿只留前后各一半,中间那截剪掉;短的停顿原样留着。

    返回按时间排好、互不重叠的几截;一处都不用剪时就是整段。
    """
    half = max_pause / 2
    kept: list[Span] = []
    cursor = 0.0
    for pause in sorted(pauses, key=lambda one: one.start):
        if pause.length <= max_pause or pause.start < cursor:
            continue
        cut_from, cut_to = pause.start + half, pause.end - half
        if cut_from > cursor:
            kept.append(Span(cursor, cut_from))
        cursor = cut_to
    if cursor < duration:
        kept.append(Span(cursor, duration))
    return kept


def join_spans(source: Path, target: Path, spans: list[Span]) -> None:
    """把 `source` 里的这几截首尾相接写进 `target`(容器按 `target` 的后缀定)。采样级裁切,不重采样。"""
    if not spans:
        raise PauseError("pauseErr_nothingLeft")
    pieces = "".join(
        f"[0:a]atrim=start={span.start:.6f}:end={span.end:.6f},asetpts=N/SR/TB[p{index}];"
        for index, span in enumerate(spans)
    )
    inputs = "".join(f"[p{index}]" for index in range(len(spans)))
    graph = f"{pieces}{inputs}concat=n={len(spans)}:v=0:a=1[out]"
    try:
        run_logged(
            [settings.ffmpeg, "-y", "-v", "error", "-i", str(source), "-filter_complex", graph, "-map", "[out]", str(target)],
            check=True, capture_output=True, timeout=600, what="压停顿",
        )
    except subprocess.SubprocessError as exc:
        raise PauseError("pauseErr_joinFailed") from exc
    if not target.is_file() or target.stat().st_size == 0:
        raise PauseError("pauseErr_joinFailed")


__all__ = [
    "DEFAULT_MAX_PAUSE",
    "MAX_PAUSE_RANGE",
    "PauseError",
    "SILENCE_FLOOR_DB",
    "Span",
    "find_pauses",
    "join_spans",
    "kept_spans",
    "parse_silences",
]
