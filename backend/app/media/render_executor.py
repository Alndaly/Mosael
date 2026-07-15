from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path

from app.media.probe import probe_has_audio
from app.media.render_plan import FILTER_PRESETS, RenderPlan

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


def _atempo_chain(speed: float) -> str:
    """atempo filters covering speed, chained because one instance is limited to [0.5, 2]."""
    if speed == 1.0:
        return ""
    parts: list[str] = []
    remaining = speed
    while remaining > 2.0:
        parts.append("atempo=2.0")
        remaining /= 2.0
    while remaining < 0.5:
        parts.append("atempo=0.5")
        remaining /= 0.5
    parts.append(f"atempo={remaining}")
    return ",".join(parts) + ","


def _fade_filters(fade_in: float, fade_out: float, duration: float, *, audio: bool) -> str:
    """Leading-comma filter suffix for edge fades in segment-local output time."""
    name = "afade" if audio else "fade"
    chunks: list[str] = []
    if fade_in > 0:
        chunks.append(f",{name}=t=in:st=0:d={fade_in}")
    if fade_out > 0:
        chunks.append(f",{name}=t=out:st={max(0.0, round(duration - fade_out, 6))}:d={fade_out}")
    return "".join(chunks)


def _srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rest = divmod(total_ms, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    secs, ms = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def _build_srt(plan: RenderPlan) -> str:
    blocks = []
    for index, item in enumerate(plan.subtitles, start=1):
        blocks.append(
            f"{index}\n{_srt_timestamp(item.start)} --> {_srt_timestamp(item.start + item.duration)}\n{item.text}\n"
        )
    return "\n".join(blocks)


def _escape_filter_path(path: Path) -> str:
    # Inside filter_complex, colons separate options and backslashes escape.
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


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
            setpts = "PTS-STARTPTS" if segment.speed == 1.0 else f"(PTS-STARTPTS)/{segment.speed}"
            video_fades = _fade_filters(segment.fade_in, segment.fade_out, segment.duration, audio=False)
            preset = f",{FILTER_PRESETS[segment.filter]}" if segment.filter else ""
            filters.append(
                f"[{input_index}:v]trim=start={src.src_in}:end={src.src_out},setpts={setpts},"
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p,setsar=1{preset}{video_fades}[v{i}]"
            )
            if probe_has_audio(path):
                tempo = _atempo_chain(segment.speed)
                audio_fades = _fade_filters(segment.fade_in, segment.fade_out, segment.duration, audio=True)
                filters.append(
                    f"[{input_index}:a]atrim=start={src.src_in}:end={src.src_out},asetpts=PTS-STARTPTS,{tempo}"
                    f"aresample={AUDIO_RATE},aformat=channel_layouts=stereo{audio_fades}[a{i}]"
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
    filters.append(f"{''.join(pair_labels)}concat=n={n}:v=1:a=1[vbase][abase]")

    # Picture-in-picture overlays from upper video tracks.
    video_label = "[vbase]"
    for i, overlay in enumerate(plan.overlays):
        path = resolve(overlay.source.file_key)
        args += ["-i", str(path)]
        src = overlay.source
        overlay_width = max(2, int(width * overlay.scale) // 2 * 2)
        filters.append(
            f"[{input_index}:v]trim=start={src.src_in}:end={src.src_out},"
            f"setpts=PTS-STARTPTS+{overlay.start}/TB,scale={overlay_width}:-2[ovv{i}]"
        )
        out_label = f"[vov{i}]"
        filters.append(
            f"{video_label}[ovv{i}]overlay=x={overlay.x}*W:y={overlay.y}*H:eof_action=pass:"
            f"enable='between(t,{overlay.start},{overlay.start + overlay.duration})'{out_label}"
        )
        video_label = out_label
        input_index += 1

    # Burned-in subtitles from subtitle tracks (SRT + libass).
    if plan.subtitles:
        srt_path = output_path.with_suffix(".srt")
        srt_path.parent.mkdir(parents=True, exist_ok=True)
        srt_path.write_text(_build_srt(plan), encoding="utf-8")
        out_label = "[vsub]"
        filters.append(f"{video_label}subtitles=filename='{_escape_filter_path(srt_path)}'{out_label}")
        video_label = out_label

    # Audio-track clips mixed over the base audio.
    audio_label = "[abase]"
    if plan.audio_overlays:
        mix_inputs = ["[abase]"]
        for i, item in enumerate(plan.audio_overlays):
            path = resolve(item.source.file_key)
            args += ["-i", str(path)]
            src = item.source
            delay_ms = int(item.start * 1000)
            audio_fades = _fade_filters(item.fade_in, item.fade_out, item.duration, audio=True)
            filters.append(
                f"[{input_index}:a]atrim=start={src.src_in}:end={src.src_out},asetpts=PTS-STARTPTS,"
                f"volume={item.gain},aresample={AUDIO_RATE},aformat=channel_layouts=stereo{audio_fades},"
                f"adelay={delay_ms}:all=1[aov{i}]"
            )
            mix_inputs.append(f"[aov{i}]")
            input_index += 1
        filters.append(f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:normalize=0[amix]")
        audio_label = "[amix]"

    args += [
        "-filter_complex",
        ";".join(filters),
        "-map",
        video_label,
        "-map",
        audio_label,
        "-t",
        str(plan.timeline_duration),
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
