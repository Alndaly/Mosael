from __future__ import annotations

import json
import mimetypes
import subprocess
from pathlib import Path
from typing import Any


def guess_kind(path: Path, content_type: str | None = None) -> str:
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
                "ffprobe",
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


def probe_has_audio(path: Path) -> bool:
    try:
        proc = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(path)],
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except Exception:
        return False
    return bool(proc.stdout.strip())


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

