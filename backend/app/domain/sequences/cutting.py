"""切分与裁剪:单点/多点切分、按源时间区间剪掉(转写驱动的编辑)。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Clip, Sequence
from app.domain.sequences._timeline import (
    MIN_CUT_REMAINDER,
    _clip_payload,
    _inherited,
    _record_operation,
    _require_clip,
    _require_sequence,
    _sliced_inherited,
)
from app.domain.sequences.errors import SequenceDomainError


@dataclass(frozen=True)
class CutClipRange:
    """Remove a source-time range from a clip (transcript-driven edit).

    The clip splits into a left part (original position) and a right part
    that ripples left to close the gap. Cuts touching an edge trim instead;
    a cut covering everything deletes the clip.
    """

    clip_id: str
    src_start: float
    src_end: float
    actor_id: str | None = None


@dataclass(frozen=True)
class SplitClip:
    """Cut a clip into two at a source-time point — nothing is removed."""

    clip_id: str
    src_time: float
    actor_id: str | None = None


def split_clip(db: Session, sequence_id: str, op: SplitClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    if not (clip.src_in + MIN_CUT_REMAINDER < op.src_time < clip.src_out - MIN_CUT_REMAINDER):
        raise SequenceDomainError("Split point must fall inside the clip")

    original = _clip_payload(clip)
    speed = clip.speed or 1.0
    common = {
        "workspace_id": sequence.workspace_id,
        "sequence_id": sequence.id,
        "track_id": clip.track_id,
        "asset_id": clip.asset_id,
        **_inherited(clip),
    }
    db.delete(clip)
    orig_in, orig_out = original["src_in"], original["src_out"]
    # 关键帧/淡变按各自的源区间重投影,否则两半各自重播整段动画、且都在切点淡一次。
    def piece_common(piece_in: float, piece_out: float) -> dict[str, Any]:
        return {**common, **_sliced_inherited(common, orig_in, orig_out, piece_in, piece_out)}

    left = Clip(
        **piece_common(orig_in, op.src_time),
        timeline_start=original["timeline_start"],
        src_in=orig_in,
        src_out=op.src_time,
    )
    right = Clip(
        **piece_common(op.src_time, orig_out),
        timeline_start=original["timeline_start"] + (op.src_time - orig_in) / speed,
        src_in=op.src_time,
        src_out=orig_out,
    )
    db.add_all([left, right])
    db.flush()
    _record_operation(
        db,
        sequence,
        kind="split_clip",
        payload={
            "clip_id": original["clip_id"],
            "src_time": op.src_time,
            "original": original,
            "created": [_clip_payload(left), _clip_payload(right)],
        },
        summary={"operation": "split_clip", "clip_id": original["clip_id"]},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def cut_clip_range(db: Session, sequence_id: str, op: CutClipRange) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    start = max(op.src_start, clip.src_in)
    end = min(op.src_end, clip.src_out)
    if end <= start:
        raise SequenceDomainError("Cut range does not intersect the clip")

    original = {
        "clip_id": clip.id,
        "track_id": clip.track_id,
        "asset_id": clip.asset_id,
        "timeline_start": clip.timeline_start,
        "src_in": clip.src_in,
        "src_out": clip.src_out,
    }
    created: list[dict[str, Any]] = []

    speed = clip.speed or 1.0
    inherited = _inherited(clip)
    keep_left = start - clip.src_in > MIN_CUT_REMAINDER
    keep_right = clip.src_out - end > MIN_CUT_REMAINDER
    right_start = clip.timeline_start + (start - clip.src_in) / speed if keep_left else clip.timeline_start

    db.delete(clip)
    if keep_left:
        left = Clip(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            track_id=original["track_id"],
            asset_id=original["asset_id"],
            timeline_start=original["timeline_start"],
            src_in=original["src_in"],
            src_out=start,
            **inherited,
        )
        db.add(left)
        db.flush()
        created.append(_clip_payload(left))
    if keep_right:
        right = Clip(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            track_id=original["track_id"],
            asset_id=original["asset_id"],
            timeline_start=right_start,
            src_in=end,
            src_out=original["src_out"],
            **inherited,
        )
        db.add(right)
        db.flush()
        created.append(_clip_payload(right))

    _record_operation(
        db,
        sequence,
        kind="apply_transcript_edit",
        payload={
            "clip_id": original["clip_id"],
            "src_start": start,
            "src_end": end,
            "original": original,
            "created": created,
        },
        summary={"operation": "apply_transcript_edit", "clip_id": original["clip_id"], "created": len(created)},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


@dataclass(frozen=True)
class CutClipRanges:
    """Remove several source-time ranges from one clip in a single operation.

    Kept pieces are laid back-to-back from the clip's original position
    (transcript-style ripple). Recorded as apply_transcript_edit so the
    existing original+created undo/redo path applies unchanged.
    """

    clip_id: str
    ranges: tuple[tuple[float, float], ...]
    actor_id: str | None = None


@dataclass(frozen=True)
class ClipRangeCuts:
    clip_id: str
    ranges: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class CutClipRangesBatch:
    """Remove ranges from several clips as one user gesture and one undo step."""

    cuts: tuple[ClipRangeCuts, ...]
    actor_id: str | None = None


def cut_clip_ranges(db: Session, sequence_id: str, op: CutClipRanges) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    edit = _apply_clip_range_cuts(db, sequence, op.clip_id, op.ranges)

    _record_operation(
        db,
        sequence,
        kind="apply_transcript_edit",
        payload=edit,
        summary={
            "operation": "apply_transcript_edit",
            "clip_id": edit["original"]["clip_id"],
            "created": len(edit["created"]),
        },
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def cut_clip_ranges_batch(db: Session, sequence_id: str, op: CutClipRangesBatch) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip_ids = [cut.clip_id for cut in op.cuts]
    if len(clip_ids) != len(set(clip_ids)):
        raise SequenceDomainError("Each clip may only appear once in a batch cut")
    edits = [_apply_clip_range_cuts(db, sequence, cut.clip_id, cut.ranges) for cut in op.cuts]
    _record_operation(
        db,
        sequence,
        kind="apply_transcript_edits_batch",
        payload={"edits": edits},
        summary={"operation": "apply_transcript_edits_batch", "clips": len(edits)},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def _apply_clip_range_cuts(
    db: Session,
    sequence: Sequence,
    clip_id: str,
    ranges: tuple[tuple[float, float], ...],
) -> dict[str, Any]:
    """Apply one clip's range cuts without committing or recording an operation."""

    clip = _require_clip(db, sequence.id, clip_id)

    clamped = sorted(
        (max(float(start), clip.src_in), min(float(end), clip.src_out))
        for start, end in ranges
        if min(float(end), clip.src_out) > max(float(start), clip.src_in)
    )
    if not clamped:
        raise SequenceDomainError("No cut range intersects the clip")
    merged: list[list[float]] = []
    for start, end in clamped:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    kept: list[tuple[float, float]] = []
    cursor_src = clip.src_in
    for start, end in merged:
        if start - cursor_src > MIN_CUT_REMAINDER:
            kept.append((cursor_src, start))
        cursor_src = max(cursor_src, end)
    if clip.src_out - cursor_src > MIN_CUT_REMAINDER:
        kept.append((cursor_src, clip.src_out))

    original = _clip_payload(clip)
    created: list[dict[str, Any]] = []
    speed = clip.speed or 1.0
    inherited = _inherited(clip)
    orig_in, orig_out = clip.src_in, clip.src_out
    db.delete(clip)
    timeline_cursor = original["timeline_start"]
    for src_start, src_end in kept:
        piece = Clip(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            track_id=original["track_id"],
            asset_id=original["asset_id"],
            timeline_start=timeline_cursor,
            src_in=src_start,
            src_out=src_end,
            # 关键帧/淡变按保留段的源区间重投影(同 split);否则每段重播整段动画、并在切口淡一次。
            **_sliced_inherited(inherited, orig_in, orig_out, src_start, src_end),
        )
        db.add(piece)
        db.flush()
        created.append(_clip_payload(piece))
        timeline_cursor += (src_end - src_start) / speed

    return {
        "clip_id": original["clip_id"],
        "ranges": [[start, end] for start, end in merged],
        "original": original,
        "created": created,
    }


@dataclass
class SplitClipPoints:
    """Split one clip into pieces at several source-time cut points, in a single op.

    Unlike cut_clip_ranges NOTHING is removed — the pieces stay at their original
    timeline positions (transcript 「按句切分」 / 单句独立成片段). Recorded as split_clip
    so the existing original+created undo/redo path applies unchanged.
    """

    clip_id: str
    src_times: tuple[float, ...]
    actor_id: str | None = None


@dataclass(frozen=True)
class ClipPointSplits:
    clip_id: str
    src_times: tuple[float, ...]


@dataclass(frozen=True)
class SplitClipPointsBatch:
    """Split several clips as one user gesture and one undo step."""

    splits: tuple[ClipPointSplits, ...]
    actor_id: str | None = None


def split_clip_at_points(db: Session, sequence_id: str, op: SplitClipPoints) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    edit = _apply_clip_point_splits(db, sequence, op.clip_id, op.src_times)
    _record_operation(
        db,
        sequence,
        kind="split_clip",
        payload=edit,
        summary={
            "operation": "split_clip",
            "clip_id": edit["original"]["clip_id"],
            "created": len(edit["created"]),
        },
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def split_clip_points_batch(db: Session, sequence_id: str, op: SplitClipPointsBatch) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip_ids = [split.clip_id for split in op.splits]
    if len(clip_ids) != len(set(clip_ids)):
        raise SequenceDomainError("Each clip may only appear once in a batch split")
    edits = [_apply_clip_point_splits(db, sequence, split.clip_id, split.src_times) for split in op.splits]
    _record_operation(
        db,
        sequence,
        kind="apply_transcript_edits_batch",
        payload={"edits": edits},
        summary={"operation": "apply_transcript_edits_batch", "clips": len(edits)},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def _apply_clip_point_splits(
    db: Session,
    sequence: Sequence,
    clip_id: str,
    src_times: tuple[float, ...],
) -> dict[str, Any]:
    """Apply one clip's point splits without committing or recording an operation."""

    clip = _require_clip(db, sequence.id, clip_id)
    speed = clip.speed or 1

    # Interior points only, sorted; drop any too close to a neighbour or to the clip ends.
    points: list[float] = []
    cursor = clip.src_in
    for value in sorted({float(point) for point in src_times}):
        if value - cursor > MIN_CUT_REMAINDER and clip.src_out - value > MIN_CUT_REMAINDER:
            points.append(value)
            cursor = value
    if not points:
        raise SequenceDomainError("No valid split point inside the clip")

    original = _clip_payload(clip)
    # _inherited(不是手写字段表):此前这里漏了 transform / muted / text_override,多点切分会把
    # 画面变换、静音、文本一并丢掉 —— 与单点切分行为不一致。
    common = {
        "workspace_id": sequence.workspace_id,
        "sequence_id": sequence.id,
        "track_id": clip.track_id,
        "asset_id": clip.asset_id,
        **_inherited(clip),
    }
    orig_in, orig_out = clip.src_in, clip.src_out
    boundaries = [clip.src_in, *points, clip.src_out]
    db.delete(clip)
    created: list[dict[str, Any]] = []
    for src_start, src_end in zip(boundaries, boundaries[1:]):
        piece = Clip(
            **{**common, **_sliced_inherited(common, orig_in, orig_out, src_start, src_end)},
            # Keep each piece where it already sits on the timeline (speed-adjusted) — a split
            # divides, it must not move anything.
            timeline_start=original["timeline_start"] + (src_start - original["src_in"]) / speed,
            src_in=src_start,
            src_out=src_end,
        )
        db.add(piece)
        db.flush()
        created.append(_clip_payload(piece))

    return {
        "clip_id": original["clip_id"],
        "src_time": points[0],
        "original": original,
        "created": created,
    }
