from __future__ import annotations

import subprocess
from pathlib import Path
from app.core.child_process import run_logged

THUMBNAIL_NAME = "thumbnail.jpg"


def thumbnail_path(asset_directory: Path) -> Path:
    return asset_directory / THUMBNAIL_NAME


def generate_thumbnail(source: Path, kind: str, asset_directory: Path) -> Path | None:
    """Best-effort thumbnail extraction; import must never fail because of it."""
    if kind == "audio":
        return None
    target = thumbnail_path(asset_directory)
    # 0.5s 跳过片头黑场;超短片段 seek 会落在片尾之后取不到帧,退回首帧再试。
    seeks = ["0.5", None] if kind == "video" else [None]
    for seek in seeks:
        args = ["ffmpeg", "-y", "-v", "error"]
        if seek is not None:
            args += ["-ss", seek]
        args += ["-i", str(source), "-frames:v", "1", "-vf", "scale=320:-2", str(target)]
        try:
            run_logged(args, check=True, capture_output=True, timeout=30, what="缩略图生成")
        except Exception:
            continue
        if target.exists() and target.stat().st_size > 0:
            return target
    return None
