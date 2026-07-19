from __future__ import annotations

import math
import subprocess
from collections.abc import Callable
from pathlib import Path

from app.core.config import settings
from app.media.probe import probe_has_audio
from app.media.render_plan import FILTER_PRESETS, RenderPlan, Transform

"""
RenderExecutor (plan §11): turns a RenderPlan into one FFmpeg invocation.
Every segment yields a normalized [vN][aN] pair (scaled/padded to the output
format, gaps as black + silence), concatenated and encoded to mp4.
"""

AUDIO_RATE = 48000
DUCK_GAIN = 0.3  # ≈ −10.5 dB: how far a ducked track drops under overlapping audio (闪避)


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


def _grade_filter(
    grade: dict[str, float],
    curves: tuple[tuple[str, str], ...] = (),
    lut_path: str = "",
) -> str:
    """Full manual grade → FFmpeg chain, ported from mibu-video's color_vf.

    Values arrive normalized to [-1, 1]; formulas below convert them back to
    the old panel's native ranges (100-based percentages, ±100 offsets, 0..100
    amounts) so exports look identical to the old app. lut_path, when set, is an
    already-escaped .cube path burned in with lut3d after the primary grade."""
    if not grade and not curves and not lut_path:
        return ""
    value = lambda key: float(grade.get(key, 0.0))  # noqa: E731
    parts: list[str] = []

    # eq: contrast/brightness(+exposure)/saturation/gamma
    contrast = 1 + value("contrast")
    bright_factor = (1 + value("brightness")) * (1 + value("exposure") / 2)
    saturation = 1 + value("saturation")
    gamma = 1 + value("gamma")
    eq_terms = []
    if abs(contrast - 1) > 0.005:
        eq_terms.append(f"contrast={contrast:.3f}")
    if abs(bright_factor - 1) > 0.005:
        eq_terms.append(f"brightness={max(-1.0, min(1.0, bright_factor - 1)):.3f}")
    if abs(saturation - 1) > 0.005:
        eq_terms.append(f"saturation={max(0.0, min(3.0, saturation)):.3f}")
    if abs(gamma - 1) > 0.005:
        eq_terms.append(f"gamma={max(0.1, min(10.0, gamma)):.3f}")
    if eq_terms:
        parts.append("eq=" + ":".join(eq_terms))

    # Tone curve: highlights/shadows/whites/blacks/fade (old-panel ±100 → v*100)
    highlights, shadows = value("highlights") * 100, value("shadows") * 100
    whites, blacks = value("whites") * 100, value("blacks") * 100
    fade = max(0.0, value("fade")) * 100
    if any(abs(v) > 0.5 for v in (highlights, shadows, whites, blacks, fade)):
        y0 = max(0.0, min(0.30, (blacks + fade * 0.6) / 500.0))
        y1 = max(0.70, min(1.0, 1.0 + whites * 0.0015 - fade * 0.0008))
        y75 = max(0.45, min(y1 - 0.02, 0.75 + highlights * 0.0015 + whites * 0.0005 - fade * 0.0003))
        y25 = max(y0 + 0.02, min(y75 - 0.02, 0.25 + shadows * 0.0015 + blacks * 0.0005 + fade * 0.0003))
        parts.append(f"curves=master='0/{y0:.3f} 0.25/{y25:.3f} 0.75/{y75:.3f} 1/{y1:.3f}'")

    if abs(value("hue")) > 0.003:
        parts.append(f"hue=h={value('hue') * 180:.1f}")
    if abs(value("temperature")) > 0.005:
        kelvin = int(max(1000, min(40000, 6500 - value("temperature") * 2500)))
        parts.append(f"colortemperature=temperature={kelvin}")
    if abs(value("vibrance")) > 0.005:
        parts.append(f"vibrance=intensity={max(-2.0, min(2.0, value('vibrance') * 2)):.3f}")
    if abs(value("tint")) > 0.005:
        parts.append(f"colorbalance=gm={max(-1.0, min(1.0, -value('tint') * 0.2)):.3f}:pl=1")
    if value("sharpen") > 0.005:
        parts.append(f"unsharp=5:5:{max(0.0, min(1.5, value('sharpen') * 1.5)):.3f}:5:5:0")
    if value("vignette") > 0.005:
        denominator = max(4.0, 20.0 - 16.0 * min(1.0, value("vignette")))
        parts.append(f"vignette=angle=PI/{denominator:.3f}")
    # User Luma/R/G/B tone curves — a separate curves= filter after the slider-derived
    # tone adjust; ffmpeg composes master∘channel internally. Specs are pre-deduped by
    # the plan (near-dup x would reject the whole chain).
    if curves:
        parts.append("curves=" + ":".join(f"{key}='{spec}'" for key, spec in curves))
    # Creative 3D LUT sits last, on top of the primary correction.
    if lut_path:
        parts.append(f"lut3d=file='{lut_path}'")
    return ("," + ",".join(parts)) if parts else ""


def _even(value: float) -> int:
    """Round to the nearest even int — H.264 needs even dimensions."""
    rounded = int(round(value))
    return rounded if rounded % 2 == 0 else rounded + 1


def _element_transform(
    in_label: str, tf: Transform, width: int, height: int, prefix: str
) -> tuple[list[str], str, int, int]:
    """Turn a frame-sized (WxH, cover-filled) element [in_label] into a scaled/rotated/faded
    element ready to overlay, matching the preview's ``translate(x·50%,y·50%) scale rotate`` +
    opacity. Returns (filters, out_label, overlay_x, overlay_y). Geometry is precomputed here
    (W/H/scale are known) so the overlay position is a plain integer, not an FFmpeg expression.

    The rotated case pads the scaled element to a square of its diagonal before rotating so the
    corners aren't clipped and the element's centre stays put — the overlay offset is then just
    centre − box/2."""
    filters: list[str] = []
    scaled_w, scaled_h = max(2, _even(width * tf.scale)), max(2, _even(height * tf.scale))
    filters.append(f"[{in_label}]scale={scaled_w}:{scaled_h}[{prefix}s]")
    label = f"{prefix}s"

    needs_alpha = tf.opacity < 1.0 or tf.rotation != 0
    if needs_alpha:
        filters.append(f"[{label}]format=yuva420p[{prefix}a]")
        label = f"{prefix}a"
    if tf.opacity < 1.0:
        filters.append(f"[{label}]colorchannelmixer=aa={tf.opacity:.4f}[{prefix}o]")
        label = f"{prefix}o"

    # Element centre in output pixels: frame centre + x·half-frame (matches transformCss).
    cx = (0.5 + tf.x * 0.5) * width
    cy = (0.5 + tf.y * 0.5) * height
    if tf.rotation != 0:
        box = max(2, _even(math.hypot(scaled_w, scaled_h)))
        pad_x, pad_y = (box - scaled_w) // 2, (box - scaled_h) // 2
        filters.append(f"[{label}]pad={box}:{box}:{pad_x}:{pad_y}:color=black@0[{prefix}p]")
        filters.append(
            f"[{prefix}p]rotate={math.radians(tf.rotation):.6f}:ow={box}:oh={box}:c=none[{prefix}r]"
        )
        label = f"{prefix}r"
        return filters, label, int(round(cx - box / 2)), int(round(cy - box / 2))
    return filters, label, int(round(cx - scaled_w / 2)), int(round(cy - scaled_h / 2))


def _fade_filters(fade_in: float, fade_out: float, duration: float, *, audio: bool) -> str:
    """Leading-comma filter suffix for edge fades in segment-local output time."""
    name = "afade" if audio else "fade"
    chunks: list[str] = []
    if fade_in > 0:
        chunks.append(f",{name}=t=in:st=0:d={fade_in}")
    if fade_out > 0:
        chunks.append(f",{name}=t=out:st={max(0.0, round(duration - fade_out, 6))}:d={fade_out}")
    return "".join(chunks)


def _ass_timestamp(seconds: float) -> str:
    total_cs = max(0, int(round(seconds * 100)))
    hours, rest = divmod(total_cs, 360_000)
    minutes, rest = divmod(rest, 6_000)
    secs, cs = divmod(rest, 100)
    return f"{hours:d}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _ass_color(hex_color: str, alpha: int = 0) -> str:
    """#RRGGBB → ASS &HAABBGGRR (alpha 0=opaque, 255=transparent)."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"&H{alpha & 0xFF:02X}{b:02X}{g:02X}{r:02X}"


def _ass_text(text: str) -> str:
    # ASS uses {} for override tags and \N for line breaks; neutralise stray braces.
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


def _build_ass(plan: RenderPlan) -> str:
    """A styled ASS subtitle file matching the preview's subtitle_style (font size in native
    frame pixels, text/box colour + box opacity, bold, position, vertical offset)."""
    style = plan.subtitle_style
    w, h = plan.output.width, plan.output.height
    align = {"bottom": 2, "center": 5, "top": 8}.get(style.position, 2)
    box_alpha = round((1.0 - style.bg_opacity) * 255)
    has_box = style.bg_opacity > 0
    border_style = 3 if has_box else 1  # 3 = opaque box (BackColour), 1 = plain/outline
    outline = round(style.font_size * 0.12) if has_box else 0  # box padding
    margin_v = 0 if style.position == "center" else round(style.offset / 100.0 * h)
    primary = _ass_color(style.color)
    back = _ass_color(style.bg_color, box_alpha)
    bold = -1 if style.bold else 0

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {w}\n"
        f"PlayResY: {h}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,Sans,{style.font_size:g},{primary},&H000000FF,{back},{back},{bold},"
        f"0,0,0,100,100,0,0,{border_style},{outline},0,{align},40,40,{margin_v},1\n\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )
    lines = [
        f"Dialogue: 0,{_ass_timestamp(item.start)},{_ass_timestamp(item.start + item.duration)},"
        f"Default,,0,0,0,,{_ass_text(item.text)}"
        for item in plan.subtitles
    ]
    return header + "\n".join(lines) + "\n"


def _escape_filter_path(path: Path) -> str:
    # Inside filter_complex, colons separate options and backslashes escape.
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _base_video_chain(input_index: int, i: int, src_in: float, src_out: float, setpts: str, width: int, height: int, fps: float, tail: str, fill_mode: str) -> str:
    """[input:v] → [vi] 的完整视频链;按画幅填充模式选择裁剪/留黑边/模糊背景。"""
    head = f"[{input_index}:v]trim=start={src_in}:end={src_out},setpts={setpts}"
    end = f",fps={fps},format=yuv420p,setsar=1{tail}[v{i}]"
    if fill_mode == "cover":
        return f"{head},scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}{end}"
    if fill_mode == "blur":
        return (
            f"{head},split=2[bg{i}][fg{i}];"
            f"[bg{i}]scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},gblur=sigma=20[bgb{i}];"
            f"[fg{i}]scale={width}:{height}:force_original_aspect_ratio=decrease[fgc{i}];"
            f"[bgb{i}][fgc{i}]overlay=(W-w)/2:(H-h)/2{end}"
        )
    # contain(留黑边)
    return f"{head},scale={width}:{height}:force_original_aspect_ratio=decrease,pad={width}:{height}:(ow-iw)/2:(oh-ih)/2{end}"


def build_ffmpeg_command(plan: RenderPlan, resolve: Callable[[str], Path], output_path: Path) -> list[str]:
    width, height, fps = plan.output.width, plan.output.height, plan.output.fps
    args: list[str] = [settings.ffmpeg, "-y", "-v", "error", "-progress", "pipe:1", "-nostats"]
    filters: list[str] = []
    pair_labels: list[str] = []
    input_index = 0

    for i, segment in enumerate(plan.video_segments):
        if segment.kind == "clip" and segment.source is not None:
            path = resolve(segment.source.file_key)
            args += ["-i", str(path)]
            src = segment.source
            setpts = "PTS-STARTPTS" if segment.speed == 1.0 else f"(PTS-STARTPTS)/{segment.speed}"
            # Picture fade (画面淡变, fade to/from black) is independent of the audio fade below.
            video_fades = _fade_filters(segment.video_fade_in, segment.video_fade_out, segment.duration, audio=False)
            preset = f",{FILTER_PRESETS[segment.filter]}" if segment.filter else ""
            lut_path = _escape_filter_path(resolve(segment.lut)) if segment.lut else ""
            preset += _grade_filter(dict(segment.grade), segment.curves, lut_path)
            if segment.transform.is_identity:
                filters.append(
                    _base_video_chain(
                        input_index, i, src.src_in, src.src_out, setpts, width, height, fps,
                        f"{preset}{video_fades}", plan.output.fill_mode,
                    )
                )
            else:
                # Free-element clip: cover-fill to frame, grade/fade, then composite over black
                # at its transform (matches the preview compositor; fill_mode is moot here since
                # the element is cover-filled like the preview's objectFit:cover).
                filters.append(
                    f"[{input_index}:v]trim=start={src.src_in}:end={src.src_out},setpts={setpts},"
                    f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
                    f"{preset}{video_fades},fps={fps},setsar=1[elt{i}]"
                )
                tfilters, tlabel, ox, oy = _element_transform(f"elt{i}", segment.transform, width, height, f"bt{i}")
                filters += tfilters
                filters.append(
                    f"color=black:s={width}x{height}:r={fps}[bg{i}];"
                    f"[bg{i}][{tlabel}]overlay={ox}:{oy},format=yuv420p,setsar=1[v{i}]"
                )
            if probe_has_audio(path) and not plan.mute_base_audio:
                tempo = _atempo_chain(segment.speed)
                audio_fades = _fade_filters(segment.fade_in, segment.fade_out, segment.duration, audio=True)
                filters.append(
                    f"[{input_index}:a]atrim=start={src.src_in}:end={src.src_out},asetpts=PTS-STARTPTS,{tempo}"
                    f"aresample={AUDIO_RATE},aformat=channel_layouts=stereo{audio_fades}[a{i}]"
                )
            else:
                # No source audio, or the base track is silenced by a solo elsewhere.
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

    # Upper-video-track clips composited over the base, each a free element at its transform
    # (cover-filled to the frame then scaled/rotated/faded — same model as the base track).
    video_label = "[vbase]"
    for i, overlay in enumerate(plan.overlays):
        path = resolve(overlay.source.file_key)
        args += ["-i", str(path)]
        src = overlay.source
        filters.append(
            f"[{input_index}:v]trim=start={src.src_in}:end={src.src_out},"
            f"setpts=PTS-STARTPTS+{overlay.start}/TB,"
            f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}[oelt{i}]"
        )
        tfilters, tlabel, ox, oy = _element_transform(f"oelt{i}", overlay.transform, width, height, f"ot{i}")
        filters += tfilters
        out_label = f"[vov{i}]"
        filters.append(
            f"{video_label}[{tlabel}]overlay=x={ox}:y={oy}:eof_action=pass:"
            f"enable='between(t,{overlay.start},{overlay.start + overlay.duration})'{out_label}"
        )
        video_label = out_label
        input_index += 1

    # Burned-in subtitles from subtitle tracks: a styled ASS file (libass) so font size,
    # colour, background box, bold, position and offset match the preview's subtitle_style.
    if plan.subtitles:
        ass_path = output_path.with_suffix(".ass")
        ass_path.parent.mkdir(parents=True, exist_ok=True)
        ass_path.write_text(_build_ass(plan), encoding="utf-8")
        out_label = "[vsub]"
        filters.append(f"{video_label}subtitles=filename='{_escape_filter_path(ass_path)}'{out_label}")
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
            # Ducking: after adelay the stream is on timeline time, so the enable windows are
            # absolute — drop to DUCK_GAIN while a non-ducked clip overlaps, full gain elsewhere.
            duck = ""
            if item.duck_windows:
                enable = "+".join(f"between(t,{a},{b})" for a, b in item.duck_windows)
                duck = f",volume=enable='{enable}':volume={DUCK_GAIN}"
            filters.append(
                f"[{input_index}:a]atrim=start={src.src_in}:end={src.src_out},asetpts=PTS-STARTPTS,"
                f"volume={item.gain},aresample={AUDIO_RATE},aformat=channel_layouts=stereo{audio_fades},"
                f"adelay={delay_ms}:all=1{duck}[aov{i}]"
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
