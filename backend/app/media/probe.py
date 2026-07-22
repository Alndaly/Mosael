from __future__ import annotations

import json
import mimetypes
import subprocess
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable
from pathlib import Path
from typing import Any

from app.core.config import settings


AUDIO_EXTENSIONS = {".m4a", ".mp3", ".wav", ".aac", ".flac", ".ogg", ".opus", ".wma"}


def guess_kind(path: Path, content_type: str | None = None) -> str:
    if path.suffix.lower() in AUDIO_EXTENSIONS:
        return "audio"
    mime = content_type or mimetypes.guess_type(path.name)[0] or ""
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("audio/"):
        return "audio"
    return "video"


def probe_media(path: Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            [
                settings.ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration:stream=codec_type,width,height,r_frame_rate",
                "-of",
                "json",
                str(path),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        return {}
    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {}
    info: dict[str, Any] = {}
    fmt = raw.get("format") or {}
    if fmt.get("duration") is not None:
        try:
            info["duration"] = float(fmt["duration"])
        except (TypeError, ValueError):
            pass
    for stream in raw.get("streams") or []:
        if stream.get("codec_type") == "video":
            info["width"] = stream.get("width")
            info["height"] = stream.get("height")
            info["fps"] = _parse_rate(stream.get("r_frame_rate"))
            break
    return {k: v for k, v in info.items() if v is not None}


def remux_in_place(path: Path) -> bool:
    """Lossless remux (`-c copy`) that rewrites the container header in place.

    MediaRecorder 直录的 webm 是流式写出的,Chromium 不回填 Duration 头,
    ffprobe 探不到时长、按时长定位的操作全部失灵。整文件无损重封装一遍,
    由 ffmpeg 写出完整的头,再重探即可。失败时保留原文件。

    .webm 后缀会推导出只收 VP8/VP9/AV1 的严格 WebM muxer;装着别的编码的
    "webm" 文件(改过扩展名等)换通用 matroska muxer 再试一次。"""
    tmp = path.with_name(path.stem + ".remux" + path.suffix)
    attempts: list[list[str]] = [[]]
    if path.suffix.lower() in {".webm", ".mkv"}:
        attempts.append(["-f", "matroska"])
    for extra in attempts:
        try:
            subprocess.run(
                [settings.ffmpeg, "-y", "-v", "error", "-i", str(path), "-c", "copy", *extra, str(tmp)],
                check=True,
                capture_output=True,
                timeout=120,
            )
        except Exception:
            tmp.unlink(missing_ok=True)
            continue
        if tmp.exists() and tmp.stat().st_size > 0:
            tmp.replace(path)
            return True
        tmp.unlink(missing_ok=True)
    return False


# ffprobe is cheap but not free; a long timeline should not fork one per source at once.
_MAX_PARALLEL_PROBES = 8


def probe_has_audio(path: Path) -> bool:
    try:
        proc = subprocess.run(
            [settings.ffprobe, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        return False
    return bool(proc.stdout.strip())


def probe_has_audio_many(paths: "Iterable[Path]") -> dict[Path, bool]:
    """probe_has_audio over many files at once.

    Building an ffmpeg command probes every optional source to find out whether it carries an
    audio stream, and each probe spawns ffprobe and waits ~30-80ms. Done in series that is a
    second or more of dead time before the render even starts, for work that is pure waiting on
    child processes — so it runs concurrently, bounded so a long timeline cannot fork hundreds
    of ffprobes at once. Deduped: the same source used by several clips is probed once.
    """
    unique = list(dict.fromkeys(paths))
    if not unique:
        return {}
    if len(unique) == 1:
        return {unique[0]: probe_has_audio(unique[0])}
    with ThreadPoolExecutor(max_workers=min(_MAX_PARALLEL_PROBES, len(unique))) as pool:
        return dict(zip(unique, pool.map(probe_has_audio, unique)))


def _parse_rate(value: str | None) -> float | None:
    if not value or value == "0/0":
        return None
    if "/" in value:
        a, b = value.split("/", 1)
        try:
            denom = float(b)
            return float(a) / denom if denom else None
        except ValueError:
            return None
    try:
        return float(value)
    except ValueError:
        return None

