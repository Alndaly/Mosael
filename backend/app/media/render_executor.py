from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from app.media.probe import probe_has_audio
from app.media.render_plan import RenderPlan

"""
RenderExecutor (plan §11): turns a RenderPlan into one FFmpeg invocation.
Every segment yields a normalized [vN][aN] pair (scaled/padded to the output
format, gaps as black + silence), concatenated and encoded to mp4.
"""

AUDIO_RATE = 48000


class RenderExecutionError(RuntimeError):
    def __init__(self, message: str, *, stderr_tail: str = "") -> None:
        super().__init__(message)
        self.stderr_tail = stderr_tail


def build_ffmpeg_command(plan: RenderPlan, resolve: Callable[[str], Path], output_path: Path) -> list[str]:
    width, height, fps = plan.output.width, plan.output.height, plan.output.fps
    args: list[str] = ["ffmpeg", "-y", "-v", "error", "-progress", "pipe:1", "-nostats"]
    filters: list[str] = []
    pair_labels: list[str] = []
    input_index = 0

    for i, segment in enumerate(plan.video_segments):
        if segment.kind == "clip" and segment.source is not None:
            path = resolve(segment.source.file_key)
            args += ["-i", str(path)]
            src = segment.source
            filters.append(
                f"[{input_index}:v]trim=start={src.src_in}:end={src.src_out},setpts=PTS-STARTPTS,"
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p,setsar=1[v{i}]"
            )
            if probe_has_audio(path):
                filters.append(
                    f"[{input_index}:a]atrim=start={src.src_in}:end={src.src_out},asetpts=PTS-STARTPTS,"
                    f"aresample={AUDIO_RATE},aformat=channel_layouts=stereo[a{i}]"
                )
            else:
                filters.append(
                    f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=0:{segment.duration}[a{i}]"
                )
            input_index += 1
        else:
            filters.append(
                f"color=black:s={width}x{height}:r={fps},trim=0:{segment.duration},format=yuv420p,setsar=1[v{i}]"
            )
            filters.append(f"anullsrc=r={AUDIO_RATE}:cl=stereo,atrim=0:{segment.duration}[a{i}]")
        pair_labels.append(f"[v{i}][a{i}]")

    n = len(plan.video_segments)
    filters.append(f"{''.join(pair_labels)}concat=n={n}:v=1:a=1[vout][aout]")

    args += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    return args


def execute_render(
    plan: RenderPlan,
    resolve: Callable[[str], Path],
    output_path: Path,
    on_progress: Callable[[float], None] | None = None,
) -> None:
    """Run FFmpeg, reporting progress in [0, 1] from -progress output."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    command = build_ffmpeg_command(plan, resolve, output_path)
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    total_us = max(plan.timeline_duration, 0.001) * 1_000_000
    assert process.stdout is not None
    for line in process.stdout:
        if on_progress and line.startswith("out_time_us="):
            try:
                on_progress(min(1.0, int(line.split("=", 1)[1]) / total_us))
            except ValueError:
                pass
    process.wait()
    if process.returncode != 0:
        stderr_tail = (process.stderr.read() if process.stderr else "")[-2000:]
        raise RenderExecutionError(
            f"FFmpeg exited with code {process.returncode}",
            stderr_tail=stderr_tail,
        )
