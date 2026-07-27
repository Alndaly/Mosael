"""Encode a stream of raw RGBA frames (from the offline canvas renderer) into an H.264 mp4.

The parity design's 方案 Y splits responsibilities cleanly: the browser's ONE canvas renderer
produces every final pixel (preview and export alike), and ffmpeg does only what canvas can't —
encode + mux. This module is that encode end for export: frames arrive as raw bytes over the wire
(the WebSocket transport pipes them straight from the frontend's OffscreenCanvas), get fed to
ffmpeg's rawvideo stdin, and come out as a faststart mp4, optionally muxed with an
already-rendered audio track (the frontend's OfflineAudioContext mixdown).

Video codec settings and the hardware/software choice are shared with the ffmpeg render_plan path
(`_video_encode_args`), so a video exported the new way encodes identically to the old one. The
default here is software libx264: frames arrive once over a socket and can't be replayed, so the
un-retryable mid-stream failure of a hardware encoder is not worth the speed — callers that can
replay the stream may opt into hardware.
"""

from __future__ import annotations

import subprocess
import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from app.core.config import settings
from app.media.render_executor import RenderExecutionError, _video_encode_args

# Bytes per pixel for the raw frame format the frontend sends. RGBA out of a canvas ImageData.
_BYTES_PER_PIXEL = {"rgba": 4, "rgb24": 3, "yuv420p": None}  # None → variable/planar, size not checked


class EncodeCancelled(RuntimeError):
    """Raised when `should_cancel` asked to stop before the stream finished."""


@dataclass(frozen=True)
class RawEncodeParams:
    """Duck-types render_plan's `output` for `_video_encode_args` (width/height/fps/crf/encode_preset)."""

    width: int
    height: int
    fps: float
    crf: int = 20
    encode_preset: str = "medium"


def encode_frames_to_mp4(
    frames: Iterable[bytes],
    params: RawEncodeParams,
    out_path: Path,
    *,
    pix_fmt: str = "rgba",
    audio_path: Path | None = None,
    use_hardware: bool = False,
    on_frame: Callable[[int], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> int:
    """Feed `frames` (each exactly width·height·bpp bytes for packed formats) to ffmpeg's rawvideo
    stdin and write `out_path`. Returns the number of frames encoded.

    `audio_path`, if given, is muxed as the audio track (aac). `on_frame(n)` reports progress after
    each frame. `should_cancel()` is polled between frames — a True kills ffmpeg and raises
    EncodeCancelled. A non-zero ffmpeg exit raises RenderExecutionError with its stderr tail.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    expected = _BYTES_PER_PIXEL.get(pix_fmt)
    frame_bytes = params.width * params.height * expected if expected else None

    args: list[str] = [
        settings.ffmpeg, "-y", "-v", "error",
        "-f", "rawvideo", "-pix_fmt", pix_fmt, "-s", f"{params.width}x{params.height}",
        "-r", f"{params.fps:g}", "-i", "pipe:0",
    ]
    if audio_path is not None:
        args += ["-i", str(audio_path)]
    args += ["-map", "0:v:0"]
    if audio_path is not None:
        args += ["-map", "1:a:0"]
    args += _video_encode_args(params, force_software=not use_hardware)
    if audio_path is not None:
        args += ["-c:a", "aac", "-b:a", "192k"]
    else:
        args += ["-an"]
    # Pin constant output frame rate (matches the ffmpeg render_plan path) + faststart moov.
    args += ["-r", f"{params.fps:g}", "-movflags", "+faststart", str(out_path)]

    process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    assert process.stdin is not None and process.stderr is not None
    # ffmpeg's stderr must be drained concurrently: if a decode/config error fills the pipe while we
    # are busy writing frames to stdin, ffmpeg blocks writing stderr and both sides deadlock.
    stderr_data = bytearray()

    def _drain() -> None:
        try:
            for chunk in iter(lambda: process.stderr.read(4096), b""):
                stderr_data.extend(chunk)
        except Exception:
            pass

    drainer = threading.Thread(target=_drain, daemon=True)
    drainer.start()

    count = 0
    cancelled = False
    try:
        for frame in frames:
            if should_cancel is not None and should_cancel():
                cancelled = True
                break
            if frame_bytes is not None and len(frame) != frame_bytes:
                raise ValueError(
                    f"frame {count} is {len(frame)} bytes, expected {frame_bytes} "
                    f"({params.width}x{params.height} {pix_fmt})"
                )
            process.stdin.write(frame)
            count += 1
            if on_frame is not None:
                on_frame(count)
    except BrokenPipeError:
        # ffmpeg exited early (bad args / decode error) — the returncode + stderr below explain it.
        pass
    finally:
        try:
            process.stdin.close()
        except Exception:
            pass

    if cancelled:
        process.kill()
        process.wait()
        drainer.join(timeout=2)
        raise EncodeCancelled()

    process.wait()
    drainer.join(timeout=5)
    if process.returncode != 0:
        raise RenderExecutionError(
            f"FFmpeg exited with code {process.returncode}",
            stderr_tail=stderr_data.decode("utf-8", errors="replace")[-4000:],
        )
    return count


__all__ = ["RawEncodeParams", "EncodeCancelled", "encode_frames_to_mp4"]
