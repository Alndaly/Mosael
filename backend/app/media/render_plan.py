from __future__ import annotations

import hashlib
import json
import re

from app.domain.sequences.operations import TRANSFORM_BOUNDS, TRANSFORM_DEFAULTS
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
    scale multiplies the frame-sized element; rotation is degrees; opacity is 0..1.

    keyframes animates scale/x/y/opacity over the clip: a flat, hashable tuple of
    (t, prop, value) where t is the clip's normalized progress 0..1 — the same per-property
    model the editor keys and previews, compiled to FFmpeg time expressions at render (see
    render_executor). Empty tuple → the static scalars above hold for the whole clip."""

    scale: float = 1.0
    x: float = 0.0
    y: float = 0.0
    rotation: float = 0.0
    opacity: float = 1.0
    keyframes: tuple[tuple[float, str, float], ...] = ()

    @property
    def is_identity(self) -> bool:
        return not self.keyframes and (self.scale, self.x, self.y, self.rotation, self.opacity) == (1.0, 0.0, 0.0, 0.0, 1.0)

    def keyed(self, prop: str) -> tuple[tuple[float, float], ...]:
        """Sorted (t, value) points for one property — empty if it isn't animated."""
        pts = sorted((t, v) for t, p, v in self.keyframes if p == prop)
        return tuple(pts)

    @property
    def animates(self) -> bool:
        return any(len(self.keyed(p)) >= 2 for p in ("scale", "x", "y", "opacity"))


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
    # A video-track clip carries its own audio (like PR/DaVinci) — gain/mute mix it.
    gain: float = 1.0
    muted: bool = False
    filter: str = ""  # one of FILTER_PRESETS or ""
    # Manual grade: sorted (name, value) pairs, names from GRADE_FIELDS, values
    # clamped to [-1, 1] (0 entries dropped). Mirrors the predecessor project's color panel.
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
    # 音量关键帧:(t, gain) 归一化时间点,让片段自带音频的增益随时间插值(volume 时间表达式)。
    gain_keyframes: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class OutputSettings:
    width: int
    height: int
    fps: float
    fill_mode: str = "cover"  # cover 裁剪 / contain 留黑边 / blur 模糊背景
    # 编码参数(导出对话框可调):CRF 越小画质越高;preset 是 x264 速度档。
    crf: int = 20
    encode_preset: str = "veryfast"


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
    # From an overlay video track: its source may have no audio stream (silent video / image),
    # so the executor probes and skips it. Audio-track clips (optional=False) are always mixed.
    optional: bool = False
    # 音量关键帧:(t, gain) 归一化时间点,让这条音频的增益随时间插值(volume 时间表达式)。
    gain_keyframes: tuple[tuple[float, float], ...] = ()


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
    # The frontend stores a CSS font stack; ASS wants one family. Resolved at burn time.
    font_family: str = ""
    # Directory holding an uploaded font file, handed to libass as fontsdir. Empty means the
    # family must already be installed on the machine doing the render.
    font_dir: str = ""


DEFAULT_SUBTITLE_STYLE = SubtitleStyleSpec()


@dataclass(frozen=True)
class TextStyleSpec:
    """花字(独立文本元素)的逐条外观:每条自带一套样式,区别于序列级统一的 SubtitleStyleSpec。
    描边/阴影编译成 ASS 的 \\bord/\\shad;定位/缩放/旋转/透明度走 transform,不放这里。"""

    font_size: float = 48.0
    color: str = "#ffffff"
    stroke_color: str = "#000000"
    stroke_width: float = 0.0
    shadow: float = 0.0
    bold: bool = True
    italic: bool = False
    align: str = "center"  # left | center | right —— 单点定位时的锚点对齐
    font_family: str = ""
    font_id: str = ""  # 上传字体 id;导出侧据此解析真实字族名与 fontsdir
    font_dir: str = ""


DEFAULT_TEXT_STYLE = TextStyleSpec()


@dataclass(frozen=True)
class TextOverlayItem:
    """video 轨上的花字:文字 + 逐条样式 + transform 定位(与画面自由元素同一套 transform)。"""

    start: float
    duration: float
    text: str
    style: TextStyleSpec = DEFAULT_TEXT_STYLE
    transform: Transform = field(default_factory=Transform)


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
    text_overlays: tuple[TextOverlayItem, ...] = ()
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
            text_overlays=self.text_overlays,
            mute_base_audio=self.mute_base_audio,
            render_plan_hash=digest,
        )


class RenderPlanError(ValueError):
    pass


GAP_EPSILON = 1e-6

_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")


# Full manual-grade field set, ported from the predecessor project's color panel. All values
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


X264_PRESETS = frozenset(
    {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"}
)


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
    text_overlays: list[dict] | None = None,
    luts: dict[str, str] | None = None,
    fill_mode: str = "cover",
    solo_active: bool = False,
    mute_base_audio: bool = False,
    crf: int = 20,
    encode_preset: str = "veryfast",
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
                gain=float(clip.get("gain", 1.0)),
                gain_keyframes=_read_gain_keyframes(effects),
                muted=bool(clip.get("muted")),
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
                gain_keyframes=_read_gain_keyframes(clip.get("effects") or {}),
                fade_in=fade_in,
                fade_out=fade_out,
                duck_windows=windows,
                optional=bool(clip.get("optional")),
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

    # 花字:video 轨上无 asset 的文本元素,每条自带样式,用 transform 定位(与画面元素同一套)。
    text_items: list[TextOverlayItem] = []
    for clip in sorted(text_overlays or [], key=lambda c: float(c["timeline_start"])):
        text = str(clip.get("text_override") or "").strip()
        if not text:
            continue
        clip_duration = float(clip["src_out"]) - float(clip["src_in"])
        if clip_duration <= 0:
            raise RenderPlanError(f"Clip {clip['id']} has non-positive duration")
        text_items.append(
            TextOverlayItem(
                start=float(clip["timeline_start"]),
                duration=round(clip_duration, 6),
                text=text,
                style=_read_text_style((clip.get("effects") or {}).get("text_style")),
                transform=_read_transform(clip),
            )
        )
        duration = max(duration, float(clip["timeline_start"]) + clip_duration)

    # 底轨(base = 最底有片段的视频轨)若比上层视频/音频/字幕短,给画面补一段尾部黑场,
    # 让视频延伸到整条时间线时长。否则视频在 base 结束处就截断——上层视频(叠加层)、音频、
    # 字幕还在往后走,画面却没了,导出比预览短一大截、内容对不上(用户报的「预览与导出完全不同」)。
    if cursor < duration - GAP_EPSILON:
        segments.append(Segment(kind="gap", duration=round(duration - cursor, 6)))

    plan = RenderPlan(
        sequence_id=sequence_id,
        sequence_revision=revision,
        timeline_duration=round(duration, 6),
        video_segments=tuple(segments),
        output=OutputSettings(
            width=width, height=height, fps=fps, fill_mode=fill_mode if fill_mode in ("cover", "contain", "blur") else "cover",
            crf=max(0, min(51, int(crf))), encode_preset=encode_preset if encode_preset in X264_PRESETS else "veryfast"
        ),
        overlays=tuple(overlays),
        audio_overlays=tuple(audio_overlays),
        subtitles=tuple(subtitles),
        subtitle_style=_read_subtitle_style(subtitle_style),
        text_overlays=tuple(text_items),
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
        font_family=str(raw.get("font_family", d.font_family) or "")[:200],
        font_dir=str(raw.get("font_dir", d.font_dir) or "")[:500],
    )


def _read_text_style(raw: dict | None) -> TextStyleSpec:
    """clip.effects.text_style → 校验过的花字样式,逐字段回落默认值。"""
    if not isinstance(raw, dict):
        return DEFAULT_TEXT_STYLE
    d = DEFAULT_TEXT_STYLE

    def num(key: str, default: float, lo: float, hi: float) -> float:
        try:
            return max(lo, min(hi, float(raw.get(key, default))))
        except (TypeError, ValueError):
            return default

    def color(key: str, default: str) -> str:
        value = str(raw.get(key, default)).strip()
        return value if _HEX_RE.match(value) else default

    align = str(raw.get("align", d.align))
    return TextStyleSpec(
        font_size=num("font_size", d.font_size, 4.0, 800.0),
        color=color("color", d.color),
        stroke_color=color("stroke_color", d.stroke_color),
        stroke_width=num("stroke_width", d.stroke_width, 0.0, 40.0),
        shadow=num("shadow", d.shadow, 0.0, 40.0),
        bold=bool(raw.get("bold", d.bold)),
        italic=bool(raw.get("italic", d.italic)),
        align=align if align in ("left", "center", "right") else d.align,
        font_family=str(raw.get("font_family", d.font_family) or "")[:200],
        font_id=str(raw.get("font_id", d.font_id) or "")[:64],
        font_dir=str(raw.get("font_dir", d.font_dir) or "")[:500],
    )


def _read_gain_keyframes(effects: dict) -> tuple[tuple[float, float], ...]:
    """clip.effects.gain_keyframes([{t,gain}]) → 排序、钳制的 (t, gain) 轨(t∈[0,1], gain∈[0,4])。
    单点或空视作无动画,由调用方走静态 gain。"""
    raw = (effects or {}).get("gain_keyframes")
    if not isinstance(raw, list):
        return ()
    pts: list[tuple[float, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            t = max(0.0, min(1.0, float(item["t"])))
            g = max(0.0, min(4.0, float(item["gain"])))
        except (KeyError, TypeError, ValueError):
            continue
        pts.append((t, g))
    return tuple(sorted(pts))


def _read_transform(clip: dict) -> Transform:
    """clip.transform → a clamped Transform.

    钳制范围与默认值来自 `domain.sequences.operations.TRANSFORM_BOUNDS` —— **全项目唯一一份**,
    Mirrors the frontend readTransform,
    由 `contracts/transform-cases.json` 钉住,前端 `readTransform` 跑同一份语料。此前这里自己
    写了一套更宽的(scale≤10、x/y±4、rotation % 360),而前端一处都不钳:同一个 clip,预览放
    20 倍、导出放 10 倍。没发作只因为写入路径先钳过一道 —— 那是上游挡住,不是两侧一致。
    """
    raw = clip.get("transform") or {}
    if not isinstance(raw, dict):
        return IDENTITY_TRANSFORM

    def num(key: str) -> float:
        default = TRANSFORM_DEFAULTS[key]
        got = raw.get(key, default)
        # **布尔不是数字。** Python 里 `float(True) == 1.0`(bool 是 int 的子类),于是
        # `{"y": true}` 会被读成 y=1.0,把片段挪到画面外;JS 那侧则当垃圾退回默认。
        # 这是契约逼出来的一处 —— 两侧对"什么算数字"要有同一个答案。
        if isinstance(got, bool):
            return default
        try:
            value = float(got)
        except (TypeError, ValueError):
            return default
        lo, hi = TRANSFORM_BOUNDS[key]
        return max(lo, min(hi, value))

    return Transform(
        scale=num("scale"),
        x=num("x"),
        y=num("y"),
        rotation=num("rotation"),
        opacity=num("opacity"),
        keyframes=_read_keyframes(raw.get("keyframes")),
    )




def _read_keyframes(raw: object) -> tuple[tuple[float, str, float], ...]:
    """[{t, scale?, x?, y?, opacity?}] → flat, clamped, sorted (t, prop, value) tuple.

    Flattened per-property so the executor can pull one property's track and compile it to a
    time expression; clamped to the same ranges as the static scalars(TRANSFORM_BOUNDS)so a
    hostile payload can't inject wild values."""
    if not isinstance(raw, list):
        return ()
    out: list[tuple[float, str, float]] = []
    for kf in raw:
        if not isinstance(kf, dict):
            continue
        try:
            t = max(0.0, min(1.0, float(kf.get("t"))))
        except (TypeError, ValueError):
            continue
        for prop, (lo, hi) in TRANSFORM_BOUNDS.items():
            value = kf.get(prop)
            if isinstance(value, (int, float)):
                out.append((round(t, 6), prop, max(lo, min(hi, float(value)))))
    return tuple(sorted(out))


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
