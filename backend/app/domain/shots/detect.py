"""量出一段视频的刀口和「画面动了多少」,把刀口变成镜头。只读文件、不碰数据库。

方法出自 reelbench-skills 的 video-shots(https://github.com/eternityspring/reelbench-skills,Apache-2.0):
ffmpeg 的 `scene` 分数找刀口;同一遍里按 5Hz 取 64×36 小图的帧间差(`tblend=difference` 的平均亮度)当动静;
每镜的动静取镜内中位数并掐掉两头;短于最短镜头的碎片并进前一镜。代码按这里的约定重写,没有照抄。

**一遍解码出两样。** 刀口和动静各要解一遍整条视频;`split` 成两路、各写一个文件,一遍就够。文件名用相对路径、
在临时目录里跑 —— 滤镜参数里的路径要转义冒号和反斜杠,Windows 的盘符、带空格的目录都会出事,相对路径没有这些。
"""

from __future__ import annotations

import re
import statistics
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.child_process import run_logged
from app.core.config import settings
from app.core.i18n import LocalizedError
from app.media.probe import probe_has_audio, probe_media

#: 刀口阈值:scene 分数超过它算一刀。0.3 对多数片子合适;暗片、慢节奏的片子会漏刀,调到 0.15。
DEFAULT_THRESHOLD = 0.3
#: 短于它的「镜头」是闪白、字幕跳变、检测误报,并进前一镜。
DEFAULT_MIN_SHOT_SECONDS = 0.3
#: 动静的采样率和小图尺寸:够分辨「整幅在动」和「没动」,又不至于让长片解得很慢。
MOTION_HZ = 5
#: 一份表最多这么多镜。再多的话一屏看不完、模型要判十几批;截断并在提示里说清(长片分段拆见 ADR 0061 后续)。
MAX_SHOTS = 240
#: 量刀口时缩到这么宽:scene 分数对分辨率不敏感,缩小只是让解码快。
SCENE_WIDTH = 320


class ShotDetectError(LocalizedError, RuntimeError):
    """量刀口失败。带文案 key(`shotsErr_*`)。"""


@dataclass(frozen=True)
class Probe:
    duration: float
    fps: float
    width: int
    height: int
    has_audio: bool

    def as_dict(self) -> dict[str, Any]:
        return {"duration": self.duration, "fps": self.fps, "width": self.width, "height": self.height,
                "has_audio": self.has_audio}


@dataclass(frozen=True)
class Measured:
    cuts: list[dict[str, float]]
    #: 动静曲线:第 i 个值是 i / MOTION_HZ 秒处和前一帧的差(0–255)。只量刀口时是空的。
    motion: list[float]


def probe(path: Path) -> Probe:
    info = probe_media(path)
    duration = float(info.get("duration") or 0)
    if duration <= 0:
        raise ShotDetectError("shotsErr_noDuration")
    if not info.get("width"):
        raise ShotDetectError("shotsErr_noVideoStream")
    return Probe(duration=duration, fps=float(info.get("fps") or 0), width=int(info.get("width") or 0),
                 height=int(info.get("height") or 0), has_audio=probe_has_audio(path))


_PTS = re.compile(r"pts_time:([0-9.]+)")
_SCORE = re.compile(r"lavfi\.scene_score=([0-9.]+)")
_YAVG = re.compile(r"lavfi\.signalstats\.YAVG=([0-9.]+)")


def _parse_cuts(text: str) -> list[dict[str, float]]:
    """`metadata=print` 的输出:一行 `frame:… pts_time:12.3`,下一行 `lavfi.scene_score=0.56`。"""
    cuts: list[dict[str, float]] = []
    at: float | None = None
    for line in text.splitlines():
        if (pts := _PTS.search(line)) is not None:
            at = float(pts.group(1))
        elif (score := _SCORE.search(line)) is not None and at is not None:
            cuts.append({"time": round(at, 3), "score": round(float(score.group(1)), 3)})
            at = None
    return cuts


def _parse_motion(text: str) -> list[float]:
    return [round(float(match.group(1)), 2) for match in _YAVG.finditer(text)]


def measure(path: Path, *, threshold: float = DEFAULT_THRESHOLD, motion: bool = True) -> Measured:
    """一遍 ffmpeg 量出刀口(和动静曲线)。`motion=False` 只量刀口 —— 分析抽帧时只要知道镜头在哪。"""
    scene = f"scale={SCENE_WIDTH}:-2,select='gt(scene,{threshold:.3f})',metadata=print:file=cuts.txt"
    with tempfile.TemporaryDirectory(prefix="mosael-shots-") as tmp:
        if motion:
            graph = (f"[0:v]split=2[s][m];[s]{scene}[so];"
                     f"[m]fps={MOTION_HZ},scale=64:36,tblend=all_mode=difference,signalstats,"
                     "metadata=print:key=lavfi.signalstats.YAVG:file=motion.txt[mo]")
            outputs = ["-map", "[so]", "-f", "null", "-", "-map", "[mo]", "-f", "null", "-"]
        else:
            graph = f"[0:v]{scene}[so]"
            outputs = ["-map", "[so]", "-f", "null", "-"]
        try:
            run_logged(
                [settings.ffmpeg, "-hide_banner", "-nostats", "-v", "error", "-i", str(path), "-an",
                 "-filter_complex", graph, *outputs],
                check=True, capture_output=True, timeout=1800, cwd=tmp, what="量刀口和动静",
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ShotDetectError("shotsErr_detectFailed") from exc
        cuts_file, motion_file = Path(tmp) / "cuts.txt", Path(tmp) / "motion.txt"
        cuts = _parse_cuts(cuts_file.read_text(encoding="utf-8", errors="replace")) if cuts_file.is_file() else []
        track = (_parse_motion(motion_file.read_text(encoding="utf-8", errors="replace"))
                 if motion and motion_file.is_file() else [])
    return Measured(cuts=cuts, motion=track)


def shot_motion(track: list[float], start: float, end: float) -> float | None:
    """这一镜的动静:镜内采样的中位数,两头各掐掉 `min(0.4, max(0.1, 镜长×0.15))` 秒 ——
    刀口两侧的差是「换了一个画面」,不是「画面在动」。镜头太短、掐完没剩采样时回 None(不评判)。"""
    if not track:
        return None
    span = end - start
    trim = min(0.4, max(0.1, span * 0.15))
    first, last = start + trim, end - trim
    #: tblend 的第 i 个值是第 i 帧和第 i-1 帧的差,落在 i / hz 秒处;第 0 帧没有前一帧,ffmpeg 不出值,所以偏一位。
    samples = [value for index, value in enumerate(track) if first <= (index + 1) / MOTION_HZ <= last]
    if not samples:
        return None
    return round(statistics.median(samples), 2)


def build_shots(duration: float, cuts: list[dict[str, float]], track: list[float], *,
                min_shot: float = DEFAULT_MIN_SHOT_SECONDS) -> list[dict[str, Any]]:
    """刀口 → 镜头。碎片(短于 `min_shot`)并进前一镜;开头那一段太短就并进后一镜。"""
    times = sorted({round(cut["time"], 3) for cut in cuts if 0 < cut["time"] < duration})
    bounds = [0.0, *times, round(duration, 3)]
    spans: list[list[float]] = []
    for start, end in zip(bounds, bounds[1:]):
        if spans and end - start < min_shot:
            spans[-1][1] = end
        else:
            spans.append([start, end])
    if len(spans) > 1 and spans[0][1] - spans[0][0] < min_shot:
        spans[1][0] = spans[0][0]
        spans.pop(0)
    shots: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(spans[:MAX_SHOTS], start=1):
        shots.append({
            "id": shot_id(index),
            "start": round(start, 3),
            "end": round(end, 3),
            "seconds": round(end - start, 3),
            "motion": shot_motion(track, start, end),
        })
    return shots


def shot_id(index: int) -> str:
    """S01、S02 …… 过了 99 镜照样往下数(S100)。"""
    return f"S{index:02d}"


__all__ = [
    "DEFAULT_MIN_SHOT_SECONDS", "DEFAULT_THRESHOLD", "MAX_SHOTS", "MOTION_HZ", "Measured", "Probe", "ShotDetectError",
    "build_shots", "measure", "probe", "shot_id", "shot_motion",
]
