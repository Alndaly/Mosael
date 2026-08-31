"""Video → GIF codec adapter. No database or job-system knowledge belongs here."""

from __future__ import annotations

import subprocess
from pathlib import Path

from app.core.child_process import run_logged
from app.core.config import settings


class GifEncodeError(RuntimeError):
    pass


def encode_video_gif(
    source: Path,
    target: Path,
    *,
    fps: int = 12,
    width: int = 720,
    start: float = 0,
    duration: float | None = None,
) -> None:
    """Encode a looping, palette-optimised GIF while preserving aspect ratio."""
    if fps < 1 or fps > 30:
        raise GifEncodeError("GIF 帧率要在 1–30 fps 之间")
    if width < 64 or width > 1920:
        raise GifEncodeError("GIF 宽度要在 64–1920 像素之间")
    if start < 0 or (duration is not None and duration <= 0):
        raise GifEncodeError("GIF 起点不能为负数，时长必须大于 0")

    # 同一次 filter graph 生成并使用调色板，比直接 `-f gif` 体积更小、渐变色带更少。
    filters = (
        f"fps={fps},scale='min({width},iw)':-2:flags=lanczos,split[a][b];"
        "[a]palettegen=max_colors=256:stats_mode=diff[p];"
        "[b][p]paletteuse=dither=sierra2_4a:diff_mode=rectangle"
    )
    args = [settings.ffmpeg, "-y", "-v", "error"]
    if start:
        args += ["-ss", f"{start:.3f}"]
    args += ["-i", str(source)]
    if duration is not None:
        args += ["-t", f"{duration:.3f}"]
    args += ["-filter_complex", filters, "-loop", "0", str(target)]
    try:
        run_logged(args, check=True, capture_output=True, timeout=1800, what="视频转 GIF")
    except (OSError, subprocess.SubprocessError) as exc:
        target.unlink(missing_ok=True)
        raise GifEncodeError("视频转 GIF 失败") from exc
    if not target.is_file() or target.stat().st_size == 0:
        raise GifEncodeError("视频转 GIF 没有产生有效文件")


__all__ = ["GifEncodeError", "encode_video_gif"]

