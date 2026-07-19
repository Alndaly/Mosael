from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field

"""
RenderPlan kernel (plan §11): converts a sequence's materialized clips into a
pure, hashable description of what to render. No SQLAlchemy, no FFmpeg —
preview and export must both consume this same semantics, and it must be
unit-testable with plain dicts.
"""


@dataclass(frozen=True)
class ClipSource:
    asset_id: str
    file_key: str
    src_in: float
    src_out: float


@dataclass(frozen=True)
class Transform:
    """A video clip's free-element placement, mirroring the preview compositor's CSS
    ``translate(x·50%, y·50%) scale(s) rotate(r)`` + opacity over a cover-filled frame box.
    x/y are center offsets in half-frame units (x=1 → center shifted right by half the frame);
    scale multiplies the frame-sized element; rotation is degrees; opacity is 0..1."""

    scale: float = 1.0
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    opacity: float = 1.0

    @property
    def is_identity(self) -> bool:
        return (self.scale, self.x, self.y, self.rotation, self.opacity) == (1.0, 0.0, 0.0, 0.0, 1.0)


IDENTITY_TRANSFORM = Transform()


@dataclass(frozen=True)
class Segment:
    """One contiguous piece of the output timeline: a clip or a gap.

    duration is output-timeline time: source duration divided by speed.
    fade_in/fade_out are the AUDIO fade lengths (afade); video_fade_in/out are the picture
    fade lengths (fade to/from black) — they're independent per the inspector's 音频/画面 split.
    """

    kind: str  # "clip" | "gap"
    duration: float
    source: ClipSource | None = None
    speed: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    video_fade_in: float = 0.0
    video_fade_out: float = 0.0
    filter: str = ""  # one of FILTER_PRESETS or ""
    # Manual grade: sorted (name, value) pairs, names from GRADE_FIELDS, values
    # clamped to [-1, 1] (0 entries dropped). Mirrors mibu-video's color panel.
    grade: tuple[tuple[str, float], ...] = ()
    # Tone curves (DaVinci-style Luma/R/G/B), pre-formatted per channel as
    # (ffmpeg_key, "x/y x/y ...") — identity channels dropped, near-dup points
    # removed at plan time. Empty when all channels are identity.
    curves: tuple[tuple[str, str], ...] = ()
    # 3D LUT file_key (resolved to a path by the executor and burned in with
    # lut3d, after the slider/curve grade). Empty when no LUT is applied.
    lut: str = ""
    # Free-element placement over the frame (Canvas Phase 1b). Identity → the clip fills
    # the frame per fill_mode (fast path); otherwise it's composited over black.
    transform: Transform = IDENTITY_TRANSFORM


@dataclass(frozen=True)
class OutputSettings:
    width: int
    height: int
    fps: float
    fill_mode: str = "cover"  # cover 裁剪 / contain 留黑边 / blur 模糊背景


@dataclass(frozen=True)
class OverlayItem:
    """An upper-video-track clip composited over the base, positioned by its transform
    (Canvas Phase 1b — every video clip is a free element, same model as the base track)."""

    start: float
    duration: float
    source: ClipSource
    transform: Transform = IDENTITY_TRANSFORM


@dataclass(frozen=True)
class AudioItem:
    """An audio-track clip mixed over the base audio."""

    start: float
    duration: float
    source: ClipSource
    gain: float
    fade_in: float = 0.0
    fade_out: float = 0.0
    # Ducking (闪避): timeline-time windows where this clip's gain is lowered because a
    # non-ducked audio source (e.g. a voiceover on another track) overlaps it.
    duck_windows: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class SubtitleItem:
    """A text clip from a subtitle track, burned in at export."""

    start: float
    duration: float
    text: str


@dataclass(frozen=True)
class SubtitleStyleSpec:
    """Sequence-level subtitle appearance, mirroring the frontend SUBTITLE_DEFAULTS so burned-in
    subs match the preview. font_size is native-frame pixels; offset is % of frame height."""

    font_size: float = 32.0
    color: str = "#ffffff"
    bg_color: str = "#000000"
    bg_opacity: float = 0.5
    bold: bool = True
    position: str = "bottom"  # bottom | center | top
    offset: float = 8.0


DEFAULT_SUBTITLE_STYLE = SubtitleStyleSpec()


@dataclass(frozen=True)
class RenderPlan:
    sequence_id: str
    sequence_revision: int
    timeline_duration: float
    video_segments: tuple[Segment, ...]
    output: OutputSettings
    overlays: tuple[OverlayItem, ...] = ()
    audio_overlays: tuple[AudioItem, ...] = ()
    subtitles: tuple[SubtitleItem, ...] = ()
    subtitle_style: SubtitleStyleSpec = DEFAULT_SUBTITLE_STYLE
    # Solo: silence the base video track's audio (a soloed track elsewhere took over).
    mute_base_audio: bool = False
    render_plan_hash: str = field(default="")

    def with_hash(self) -> "RenderPlan":
        digest = hashlib.sha256(
            json.dumps(asdict(self), sort_keys=True, default=str).encode()
        ).hexdigest()[:32]
        return RenderPlan(
            sequence_id=self.sequence_id,
            sequence_revision=self.sequence_revision,
            timeline_duration=self.timeline_duration,
            video_segments=self.video_segments,
            output=self.output,
            overlays=self.overlays,
            audio_overlays=self.audio_overlays,
            subtitles=self.subtitles,
            subtitle_style=self.subtitle_style,
            mute_base_audio=self.mute_base_audio,
            render_plan_hash=digest,
        )


class RenderPlanError(ValueError):
    pass


GAP_EPSILON = 1e-6

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


# Full manual-grade field set, ported from mibu-video's color panel. All values
# are normalized to [-1, 1] in clip effects.color; the executor maps them onto
# the same FFmpeg formulas the old app used (eq/curves/hue/colortemperature/
# vibrance/colorbalance/unsharp/vignette).
GRADE_FIELDS = (
    "exposure",
    "brightness",
    "contrast",
    "gamma",
    "highlights",
    "shadows",
    "whites",
    "blacks",
    "temperature",
    "tint",
    "saturation",
    "vibrance",
    "hue",
    "fade",
    "sharpen",
    "vignette",
)


# Preset name → FFmpeg video filter chain. The plan stores only the name so it
# stays pure; the executor appends the chain. Keep in sync with the frontend
# CSS preview approximations.
FILTER_PRESETS = {
    "bw": "hue=s=0",
    "warm": "eq=saturation=1.12:gamma_r=1.06:gamma_b=0.92",
    "cool": "eq=saturation=1.08:gamma_r=0.94:gamma_b=1.08",
    "vivid": "eq=saturation=1.35:contrast=1.08",
    "fade": "eq=saturation=0.78:contrast=0.92:brightness=0.04",
}


def build_render_plan(
    *,
    sequence_id: str,
    revision: int,
    width: int,
    height: int,
    fps: float,
    clips: list[dict],
    assets: dict[str, dict],
    overlay_clips: list[dict] | None = None,
    audio_clips: list[dict] | None = None,
    subtitle_clips: list[dict] | None = None,
    subtitle_style: dict | None = None,
    luts: dict[str, str] | None = None,
    fill_mode: str = "cover",
    solo_active: bool = False,
    mute_base_audio: bool = False,
) -> RenderPlan:
    """
    clips: [{id, asset_id, timeline_start, src_in, src_out}] from the base video track.
    overlay_clips: clips from upper video tracks (may carry effects.pip {x,y,scale}).
    audio_clips: clips from audio tracks ({..., gain, muted}).
    assets: {asset_id: {file_key}}.
    Overlaps on the base track are rejected; gaps become black/silent segments.
    """
    ordered = sorted(clips, key=lambda c: float(c["timeline_start"]))
    segments: list[Segment] = []
    cursor = 0.0
    for clip in ordered:
        start = float(clip["timeline_start"])
        speed = float(clip.get("speed") or 1.0)
        if not (0.25 <= speed <= 4.0):
            raise RenderPlanError(f"Clip {clip['id']} has speed outside [0.25, 4]")
        duration = (float(clip["src_out"]) - float(clip["src_in"])) / speed
        if duration <= 0:
            raise RenderPlanError(f"Clip {clip['id']} has non-positive duration")
        if start < cursor - GAP_EPSILON:
            raise RenderPlanError(f"Clip {clip['id']} overlaps the previous clip")
        asset = assets.get(clip["asset_id"])
        if asset is None or not asset.get("file_key"):
            raise RenderPlanError(f"Clip {clip['id']} references an asset without a file")
        if start > cursor + GAP_EPSILON:
            segments.append(Segment(kind="gap", duration=round(start - cursor, 6)))
        fade_in, fade_out = _clip_fades(clip, duration)
        video_fade_in, video_fade_out = _video_fades(clip, duration)
        effects = clip.get("effects") or {}
        preset = str(effects.get("filter") or "")
        if preset and preset not in FILTER_PRESETS:
            raise RenderPlanError(f"Clip {clip['id']} uses unknown filter preset {preset!r}")
        grade = effects.get("color") or {}
        lut_id = str(grade.get("lut") or "")
        lut_key = ""
        if lut_id:
            lut_key = (luts or {}).get(lut_id, "")
            if not lut_key:
                raise RenderPlanError(f"Clip {clip['id']} references an unknown LUT {lut_id!r}")
        segments.append(
            Segment(
                kind="clip",
                duration=round(duration, 6),
                source=ClipSource(
                    asset_id=clip["asset_id"],
                    file_key=asset["file_key"],
                    src_in=float(clip["src_in"]),
                    src_out=float(clip["src_out"]),
                ),
                speed=speed,
                fade_in=fade_in,
                fade_out=fade_out,
                video_fade_in=video_fade_in,
                video_fade_out=video_fade_out,
                filter=preset,
                grade=tuple(
                    (field, _grade_value(grade, field))
                    for field in GRADE_FIELDS
                    if _grade_value(grade, field)
                ),
                curves=_curve_specs(grade.get("curves")),
                lut=lut_key,
                transform=_read_transform(clip),
            )
        )
        cursor = start + duration

    if not segments:
        raise RenderPlanError("Sequence has no clips to render")

    duration = cursor
    overlays: list[OverlayItem] = []
    for clip in sorted(overlay_clips or [], key=lambda c: float(c["timeline_start"])):
        source = _require_source(assets, clip)
        clip_duration = float(clip["src_out"]) - float(clip["src_in"])
        if clip_duration <= 0:
            raise RenderPlanError(f"Clip {clip['id']} has non-positive duration")
        overlays.append(
            OverlayItem(
                start=float(clip["timeline_start"]),
                duration=round(clip_duration, 6),
                source=source,
                transform=_read_transform(clip),
            )
        )
        duration = max(duration, float(clip["timeline_start"]) + clip_duration)

    # Solo silences non-soloed clips; then a ducked clip's gain is lowered during windows
    # where a non-ducked audible clip (e.g. a voiceover on another track) overlaps it.
    audible: list[tuple[dict, ClipSource, float, float]] = []
    for clip in sorted(audio_clips or [], key=lambda c: float(c["timeline_start"])):
        if clip.get("muted"):
            continue
        if solo_active and not clip.get("solo"):
            continue
        source = _require_source(assets, clip)
        clip_duration = float(clip["src_out"]) - float(clip["src_in"])
        if clip_duration <= 0:
            raise RenderPlanError(f"Clip {clip['id']} has non-positive duration")
        audible.append((clip, source, float(clip["timeline_start"]), clip_duration))

    key_spans = [(start, start + dur) for clip, _, start, dur in audible if not clip.get("duck")]
    audio_overlays: list[AudioItem] = []
    for clip, source, start, clip_duration in audible:
        fade_in, fade_out = _clip_fades(clip, clip_duration)
        windows = _duck_windows(start, start + clip_duration, key_spans) if clip.get("duck") else ()
        audio_overlays.append(
            AudioItem(
                start=start,
                duration=round(clip_duration, 6),
                source=source,
                gain=float(clip.get("gain", 1.0)),
                fade_in=fade_in,
                fade_out=fade_out,
                duck_windows=windows,
            )
        )
        duration = max(duration, start + clip_duration)

    subtitles: list[SubtitleItem] = []
    for clip in sorted(subtitle_clips or [], key=lambda c: float(c["timeline_start"])):
        text = str(clip.get("text_override") or "").strip()
        if not text:
            continue
        clip_duration = float(clip["src_out"]) - float(clip["src_in"])
        if clip_duration <= 0:
            raise RenderPlanError(f"Clip {clip['id']} has non-positive duration")
        subtitles.append(
            SubtitleItem(start=float(clip["timeline_start"]), duration=round(clip_duration, 6), text=text)
        )

    plan = RenderPlan(
        sequence_id=sequence_id,
        sequence_revision=revision,
        timeline_duration=round(duration, 6),
        video_segments=tuple(segments),
        output=OutputSettings(
            width=width, height=height, fps=fps, fill_mode=fill_mode if fill_mode in ("cover", "contain", "blur") else "cover"
        ),
        overlays=tuple(overlays),
        audio_overlays=tuple(audio_overlays),
        subtitles=tuple(subtitles),
        subtitle_style=_read_subtitle_style(subtitle_style),
        mute_base_audio=mute_base_audio,
    )
    return plan.with_hash()


def _duck_windows(
    start: float, end: float, key_spans: list[tuple[float, float]]
) -> tuple[tuple[float, float], ...]:
    """Merged timeline-time windows within [start, end] that overlap any key span (the spans of
    non-ducked audible clips). These are where a ducked clip's gain gets lowered."""
    raw = sorted(
        (max(start, k0), min(end, k1)) for k0, k1 in key_spans if min(end, k1) - max(start, k0) > 0.01
    )
    if not raw:
        return ()
    merged: list[list[float]] = [list(raw[0])]
    for lo, hi in raw[1:]:
        if lo <= merged[-1][1] + 0.01:
            merged[-1][1] = max(merged[-1][1], hi)
        else:
            merged.append([lo, hi])
    return tuple((round(lo, 6), round(hi, 6)) for lo, hi in merged)


def _read_subtitle_style(raw: dict | None) -> SubtitleStyleSpec:
    """sequence.subtitle_style → a validated spec, falling back to defaults per field."""
    if not isinstance(raw, dict):
        return DEFAULT_SUBTITLE_STYLE
    d = DEFAULT_SUBTITLE_STYLE

    def num(key: str, default: float, lo: float, hi: float) -> float:
        try:
            return max(lo, min(hi, float(raw.get(key, default))))
        except (TypeError, ValueError):
            return default

    def color(key: str, default: str) -> str:
        value = str(raw.get(key, default)).strip()
        return value if _HEX_RE.match(value) else default

    position = str(raw.get("position", d.position))
    return SubtitleStyleSpec(
        font_size=num("font_size", d.font_size, 4.0, 400.0),
        color=color("color", d.color),
        bg_color=color("bg_color", d.bg_color),
        bg_opacity=num("bg_opacity", d.bg_opacity, 0.0, 1.0),
        bold=bool(raw.get("bold", d.bold)),
        position=position if position in ("bottom", "center", "top") else d.position,
        offset=num("offset", d.offset, 0.0, 100.0),
    )


def _read_transform(clip: dict) -> Transform:
    """clip.transform → a clamped Transform. Mirrors the frontend readTransform defaults so
    export matches preview; out-of-range/garbage values fall back to identity components."""
    raw = clip.get("transform") or {}
    if not isinstance(raw, dict):
        return IDENTITY_TRANSFORM

    def num(key: str, default: float) -> float:
        try:
            return float(raw.get(key, default))
        except (TypeError, ValueError):
            return default

    return Transform(
        scale=max(0.01, min(10.0, num("scale", 1.0))),
        x=max(-4.0, min(4.0, num("x", 0.0))),
        y=max(-4.0, min(4.0, num("y", 0.0))),
        rotation=num("rotation", 0.0) % 360.0,
        opacity=max(0.0, min(1.0, num("opacity", 1.0))),
    )


def _grade_value(grade: dict, key: str) -> float:
    """Manual color values clamped to [-1, 1]; anything unparsable is 0."""
    try:
        return max(-1.0, min(1.0, float(grade.get(key) or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _curve_spec(points: object) -> str:
    """One channel's points → ffmpeg curves spec ``"x/y x/y ..."``, or "" if identity.

    ffmpeg's curves filter rejects the WHOLE chain ("points too close / not strictly
    increasing") if two points round to the same x at .3f — since color and subtitle
    burn-in share this vf, one bad point would crash both. So drop near-duplicates
    (< 0.004 apart) rather than let it through."""
    if not isinstance(points, (list, tuple)):
        return ""
    valid: list[tuple[float, float]] = []
    for p in points:
        if isinstance(p, (list, tuple)) and len(p) == 2:
            try:
                valid.append((max(0.0, min(1.0, float(p[0]))), max(0.0, min(1.0, float(p[1])))))
            except (TypeError, ValueError):
                continue
    if len(valid) < 2:
        return ""
    valid.sort()
    deduped: list[tuple[float, float]] = []
    for x, y in valid:
        if deduped and x - deduped[-1][0] < 0.004:
            continue
        deduped.append((x, y))
    if len(deduped) < 2:
        return ""
    if len(deduped) == 2 and deduped[0] == (0.0, 0.0) and deduped[1] == (1.0, 1.0):
        return ""  # identity → skip
    return " ".join(f"{x:.3f}/{y:.3f}" for x, y in deduped)


def _curve_specs(curves: object) -> tuple[tuple[str, str], ...]:
    """{luma|r|g|b: points} → ffmpeg per-channel specs. ffmpeg composes master∘channel."""
    if not isinstance(curves, dict):
        return ()
    out: list[tuple[str, str]] = []
    for channel, ff_key in (("luma", "master"), ("r", "r"), ("g", "g"), ("b", "b")):
        spec = _curve_spec(curves.get(channel))
        if spec:
            out.append((ff_key, spec))
    return tuple(out)


def _fades(clip: dict, duration: float, in_key: str, out_key: str) -> tuple[float, float]:
    """Fade lengths from clip effects (in_key/out_key), clamped so in+out never exceed the clip."""
    effects = clip.get("effects") or {}
    fade_in = max(0.0, float(effects.get(in_key) or 0.0))
    fade_out = max(0.0, float(effects.get(out_key) or 0.0))
    total = fade_in + fade_out
    if total > duration and total > 0:
        ratio = duration / total
        fade_in *= ratio
        fade_out *= ratio
    return round(fade_in, 6), round(fade_out, 6)


def _clip_fades(clip: dict, duration: float) -> tuple[float, float]:
    """Audio fade lengths (afade) — the inspector's 音频淡变."""
    return _fades(clip, duration, "fade_in", "fade_out")


def _video_fades(clip: dict, duration: float) -> tuple[float, float]:
    """Picture fade lengths (fade to/from black) — the inspector's 画面淡变, independent of audio."""
    return _fades(clip, duration, "video_fade_in", "video_fade_out")


def _require_source(assets: dict[str, dict], clip: dict) -> ClipSource:
    asset = assets.get(clip["asset_id"])
    if asset is None or not asset.get("file_key"):
        raise RenderPlanError(f"Clip {clip['id']} references an asset without a file")
    return ClipSource(
        asset_id=clip["asset_id"],
        file_key=asset["file_key"],
        src_in=float(clip["src_in"]),
        src_out=float(clip["src_out"]),
    )
