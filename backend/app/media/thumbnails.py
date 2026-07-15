from __future__ import annotations

import subprocess
from pathlib import Path

THUMBNAIL_NAME = "thumbnail.jpg"


def thumbnail_path(asset_directory: Path) -> Path:
    return asset_directory / THUMBNAIL_NAME


def generate_thumbnail(source: Path, kind: str, asset_directory: Path) -> Path | None:
    """Best-effort thumbnail extraction; import must never fail because of it."""
    if kind == "audio":
        return None
    target = thumbnail_path(asset_directory)
    args = ["ffmpeg", "-y", "-v", "error"]
    if kind == "video":
        args += ["-ss", "0.5"]
    args += ["-i", str(source), "-frames:v", "1", "-vf", "scale=320:-2", str(target)]
    try:
        subprocess.run(args, check=True, capture_output=True, timeout=30)
    except Exception:
        return None
    return target if target.exists() else None
