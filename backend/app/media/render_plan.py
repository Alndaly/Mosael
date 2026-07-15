from __future__ import annotations

import hashlib
import json
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
class Segment:
    """One contiguous piece of the output timeline: a clip or a gap.

    duration is output-timeline time: source duration divided by speed.
    fade_in/fade_out are output-time seconds applied at the segment edges.
    """

    kind: str  # "clip" | "gap"
    duration: float
    source: ClipSource | None = None
    speed: float = 1.0
    fade_in: float = 0.0
    fade_out: float = 0.0


@dataclass(frozen=True)
class OutputSettings:
    width: int
    height: int
    fps: float


@dataclass(frozen=True)
class OverlayItem:
    """A picture-in-picture layer from an upper video track."""

    start: float
    duration: float
    source: ClipSource
    x: float  # 0..1 of output width
    y: float  # 0..1 of output height
    scale: float  # 0..1 of output width


@dataclass(frozen=True)
class AudioItem:
    """An audio-track clip mixed over the base audio."""

    start: float
    duration: float
    source: ClipSource
    gain: float
    fade_in: float = 0.0
    fade_out: float = 0.0


@dataclass(frozen=True)
class RenderPlan:
    sequence_id: str
    sequence_revision: int
    timeline_duration: float
    video_segments: tuple[Segment, ...]
    output: OutputSettings
    overlays: tuple[OverlayItem, ...] = ()
    audio_overlays: tuple[AudioItem, ...] = ()
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
            render_plan_hash=digest,
        )


class RenderPlanError(ValueError):
    pass


GAP_EPSILON = 1e-6


DEFAULT_PIP = {"x": 0.62, "y": 0.06, "scale": 0.33}


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
            )
        )
        cursor = start + duration

    if not segments:
        raise RenderPlanError("Sequence has no clips to render")

    duration = cursor
    overlays: list[OverlayItem] = []
    for clip in sorted(overlay_clips or [], key=lambda c: float(c["timeline_start"])):
        source = _require_source(assets, clip)
        pip = {**DEFAULT_PIP, **((clip.get("effects") or {}).get("pip") or {})}
        clip_duration = float(clip["src_out"]) - float(clip["src_in"])
        if clip_duration <= 0:
            raise RenderPlanError(f"Clip {clip['id']} has non-positive duration")
        overlays.append(
            OverlayItem(
                start=float(clip["timeline_start"]),
                duration=round(clip_duration, 6),
                source=source,
                x=float(pip["x"]),
                y=float(pip["y"]),
                scale=float(pip["scale"]),
            )
        )
        duration = max(duration, float(clip["timeline_start"]) + clip_duration)

    audio_overlays: list[AudioItem] = []
    for clip in sorted(audio_clips or [], key=lambda c: float(c["timeline_start"])):
        if clip.get("muted"):
            continue
        source = _require_source(assets, clip)
        clip_duration = float(clip["src_out"]) - float(clip["src_in"])
        if clip_duration <= 0:
            raise RenderPlanError(f"Clip {clip['id']} has non-positive duration")
        fade_in, fade_out = _clip_fades(clip, clip_duration)
        audio_overlays.append(
            AudioItem(
                start=float(clip["timeline_start"]),
                duration=round(clip_duration, 6),
                source=source,
                gain=float(clip.get("gain", 1.0)),
                fade_in=fade_in,
                fade_out=fade_out,
            )
        )
        duration = max(duration, float(clip["timeline_start"]) + clip_duration)

    plan = RenderPlan(
        sequence_id=sequence_id,
        sequence_revision=revision,
        timeline_duration=round(duration, 6),
        video_segments=tuple(segments),
        output=OutputSettings(width=width, height=height, fps=fps),
        overlays=tuple(overlays),
        audio_overlays=tuple(audio_overlays),
    )
    return plan.with_hash()


def _clip_fades(clip: dict, duration: float) -> tuple[float, float]:
    """Fade lengths from clip effects, clamped so in+out never exceed the clip."""
    effects = clip.get("effects") or {}
    fade_in = max(0.0, float(effects.get("fade_in") or 0.0))
    fade_out = max(0.0, float(effects.get("fade_out") or 0.0))
    total = fade_in + fade_out
    if total > duration and total > 0:
        ratio = duration / total
        fade_in *= ratio
        fade_out *= ratio
    return round(fade_in, 6), round(fade_out, 6)


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
