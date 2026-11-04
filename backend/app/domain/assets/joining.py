"""把续写出来的几段接成一条视频,登记成新素材。原来那几段不动。

一镜比模型一次能出的长时,这一镜是几段续写接起来的(整片模板的 `extend_shot`)。接成一份素材之后,时间线、口播对齐、
字幕都还是「一镜一份素材」,不用知道它是接出来的。

接缝不按秒数算:续写的成片以上一段的尾巴开头,这段尾巴的长度不可靠(见 media/seam.py)。
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.child_process import run_logged
from app.core.config import settings
from app.core.i18n import LocalizedError
from app.db.models import Asset
from app.domain.assets.importer import register_file_asset
from app.domain.assets.lineage import CONCAT, derived
from app.media.paths import resolve_key
from app.media.probe import probe_has_audio
from app.media.seam import find_seam


class JoinError(LocalizedError, ValueError):
    """这几段接不起来。带文案 key。"""


def _concat(sources: list[Path], starts: list[float], target: Path) -> None:
    """按 `starts` 去掉每段开头那一截,首尾相接。几段都有声音才带声音:缺一段的话声音和画面就错开了。"""
    audio = all(probe_has_audio(one) for one in sources)
    inputs = [arg for source, start in zip(sources, starts) for arg in ("-ss", f"{start:.3f}", "-i", str(source))]
    streams = "".join(f"[{index}:v:0]" + (f"[{index}:a:0]" if audio else "") for index in range(len(sources)))
    graph = f"{streams}concat=n={len(sources)}:v=1:a={1 if audio else 0}[v]" + ("[a]" if audio else "")
    args = [settings.ffmpeg, "-y", "-v", "error", *inputs, "-filter_complex", graph, "-map", "[v]",
            *(["-map", "[a]", "-c:a", "aac"] if audio else []),
            #: 模型交回的片子音轨常比画面长几十毫秒,concat 按长的对齐。恒定帧率的话这段空白被重复帧补上,接缝处顿一下。
            "-fps_mode", "vfr", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(target)]
    try:
        run_logged(args, check=True, capture_output=True, timeout=600, what="接视频")
    except subprocess.SubprocessError as exc:
        raise JoinError("joinErr_failed") from exc


def join_segments(db: Session, segments: list[Asset], *, search_seconds: float, name: str = "") -> Asset:
    """把几段接成一份新素材。只有一段就是它自己。`search_seconds` 是 0 时每段从头接(只交了一帧的续写,没有重叠)。"""
    if len(segments) == 1:
        return segments[0]
    sources = [resolve_key(one.file_key) for one in segments]
    starts = [0.0]
    for index in range(1, len(segments)):
        fps = float((segments[index].media_info or {}).get("fps") or 24)
        starts.append(find_seam(sources[index - 1], sources[index], search_seconds=search_seconds, fps=fps) if search_seconds else 0.0)
    with tempfile.TemporaryDirectory(prefix="mosael-join-") as folder:
        target = Path(folder) / "joined.mp4"
        _concat(sources, starts, target)
        return register_file_asset(
            db, workspace_id=segments[0].workspace_id, project_id=segments[0].project_id, source_path=target,
            name=name or segments[0].name, source="generated", derived_from=derived(CONCAT, *(one.id for one in segments)),
        )
