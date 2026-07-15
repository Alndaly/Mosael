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
    """One contiguous piece of the output timeline: a clip or a gap."""

    kind: str  # "clip" | "gap"
    duration: float
    source: ClipSource | None = None


@dataclass(frozen=True)
class OutputSettings:
    width: int
    height: int
    fps: float


@dataclass(frozen=True)
class RenderPlan:
    sequence_id: str
    sequence_revision: int
    timeline_duration: float
    video_segments: tuple[Segment, ...]
    output: OutputSettings
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
            render_plan_hash=digest,
        )


class RenderPlanError(ValueError):
    pass


GAP_EPSILON = 1e-6


def build_render_plan(
    *,
    sequence_id: str,
    revision: int,
    width: int,
    height: int,
    fps: float,
    clips: list[dict],
    assets: dict[str, dict],
) -> RenderPlan:
    """
    clips: [{id, asset_id, timeline_start, src_in, src_out}] from the video track.
    assets: {asset_id: {file_key}}.
    Overlaps are rejected; gaps become black/silent segments.
    """
    ordered = sorted(clips, key=lambda c: float(c["timeline_start"]))
    segments: list[Segment] = []
    cursor = 0.0
    for clip in ordered:
        start = float(clip["timeline_start"])
        duration = float(clip["src_out"]) - float(clip["src_in"])
        if duration <= 0:
            raise RenderPlanError(f"Clip {clip['id']} has non-positive duration")
        if start < cursor - GAP_EPSILON:
            raise RenderPlanError(f"Clip {clip['id']} overlaps the previous clip")
        asset = assets.get(clip["asset_id"])
        if asset is None or not asset.get("file_key"):
            raise RenderPlanError(f"Clip {clip['id']} references an asset without a file")
        if start > cursor + GAP_EPSILON:
            segments.append(Segment(kind="gap", duration=round(start - cursor, 6)))
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
            )
        )
        cursor = start + duration

    if not segments:
        raise RenderPlanError("Sequence has no clips to render")

    plan = RenderPlan(
        sequence_id=sequence_id,
        sequence_revision=revision,
        timeline_duration=round(cursor, 6),
        video_segments=tuple(segments),
        output=OutputSettings(width=width, height=height, fps=fps),
    )
    return plan.with_hash()
