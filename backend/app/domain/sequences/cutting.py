"""切分与裁剪:单点/多点切分、按源时间区间剪掉(转写驱动的编辑)。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Clip, Sequence
from app.domain.sequences._timeline import (
    MIN_CUT_REMAINDER,
    _inherited,
    _record_operation,
    _require_clip,
    _require_sequence,
    _sliced_inherited,
)
from app.domain.sequences.errors import SequenceDomainError
from app.domain.sequences.coverage import EPS, clip_end
from app.domain.sequences.journal import Journal
from app.domain.sequences.links import linked_members, new_link_group


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
    #: 链接组一起切(视频在这一刻切开,链接音频也在同一刻切开);False = 只切这一段。见 links.py。
    linked: bool = True
    actor_id: str | None = None


def split_clip(db: Session, sequence_id: str, op: SplitClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    if not (clip.src_in + MIN_CUT_REMAINDER < op.src_time < clip.src_out - MIN_CUT_REMAINDER):
        raise SequenceDomainError("Split point must fall inside the clip")
    journal = Journal(db, sequence)
    _split_linked(journal, clip, [op.src_time], linked=op.linked)
    _record_operation(
        db,
        sequence,
        kind="split_clip",
        payload={"clip_id": op.clip_id, "src_time": op.src_time, "changes": journal.entries},
        summary={"operation": "split_clip", "clip_id": op.clip_id},
        actor_id=op.actor_id,
    )
    return sequence


def _split_linked(journal: Journal, clip: Clip, src_points: list[float], *, linked: bool) -> None:
    """在这几个源时间点切开一个片段,链接组员在**同一时间线时刻**跟着切开。

    切完之后谁和谁一组:时间线上同一截里的一组 —— 左半跟左半、右半跟右半(最左一截留着原来的组号,
    往右每一截一个新组号)。整组一起拖的时候,拖走的是画和它自己那一截声音。
    """
    speed = clip.speed or 1.0
    times = [clip.timeline_start + (point - clip.src_in) / speed for point in src_points]
    groups = [clip.link_group] + [new_link_group() if clip.link_group else None for _ in times]

    def group_at(start: float) -> str | None:
        return groups[sum(1 for time in times if time <= start + EPS)]

    members = linked_members(journal.db, [clip], linked=linked)
    _split_into_pieces(journal, clip, [clip.src_in, *src_points, clip.src_out], group_at)
    for member in members:
        member_speed = member.speed or 1.0
        cuts = _interior_times(member, times)
        if not cuts:
            journal.update(member, link_group=group_at(member.timeline_start))
            continue
        boundaries = [member.src_in + (time - member.timeline_start) * member_speed for time in cuts]
        _split_into_pieces(journal, member, [member.src_in, *boundaries, member.src_out], group_at)


def _interior_times(clip: Clip, times: list[float]) -> list[float]:
    """落在片段里面、离两头和彼此都不少于最小余量(源时间)的切点。"""
    speed = clip.speed or 1.0
    kept: list[float] = []
    previous = clip.timeline_start
    for time in sorted(times):
        if (time - previous) * speed > MIN_CUT_REMAINDER and (clip_end(clip) - time) * speed > MIN_CUT_REMAINDER:
            kept.append(time)
            previous = time
    return kept


def _split_into_pieces(
    journal: Journal, clip: Clip, boundaries: list[float], group_at: Callable[[float], str | None]
) -> list[Clip]:
    """按源时间边界把一个片段换成几段,每段留在它原来在时间线上的位置 —— 切分只是分开,不挪任何东西。

    关键帧 / 淡变按各自的源区间重投影,否则每段各自重播整段动画、且都在切点淡一次。
    每一段进哪个链接组由 `group_at(这一段的起点)` 说。
    """
    speed = clip.speed or 1.0
    orig_start, orig_in, orig_out = clip.timeline_start, clip.src_in, clip.src_out
    common = {
        "workspace_id": clip.workspace_id,
        "sequence_id": clip.sequence_id,
        "track_id": clip.track_id,
        "asset_id": clip.asset_id,
        **_inherited(clip),
    }
    journal.delete(clip)
    pieces: list[Clip] = []
    for piece_in, piece_out in zip(boundaries, boundaries[1:]):
        start = orig_start + (piece_in - orig_in) / speed
        pieces.append(
            journal.create(
                Clip(
                    **{**common, **_sliced_inherited(common, orig_in, orig_out, piece_in, piece_out)},
                    timeline_start=start,
                    src_in=piece_in,
                    src_out=piece_out,
                    link_group=group_at(start),
                )
            )
        )
    return pieces


def cut_clip_range(db: Session, sequence_id: str, op: CutClipRange) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    if min(op.src_end, clip.src_out) <= max(op.src_start, clip.src_in):
        raise SequenceDomainError("Cut range does not intersect the clip")
    journal = Journal(db, sequence)
    _apply_clip_range_cuts(journal, clip.id, ((op.src_start, op.src_end),))
    _record_operation(
        db,
        sequence,
        kind="apply_transcript_edit",
        payload={"clip_id": op.clip_id, "changes": journal.entries},
        summary={"operation": "apply_transcript_edit", "clip_id": op.clip_id},
        actor_id=op.actor_id,
    )
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
    journal = Journal(db, sequence)
    _apply_clip_range_cuts(journal, op.clip_id, op.ranges)
    _record_operation(
        db,
        sequence,
        kind="apply_transcript_edit",
        payload={"clip_id": op.clip_id, "changes": journal.entries},
        summary={"operation": "apply_transcript_edit", "clip_id": op.clip_id},
        actor_id=op.actor_id,
    )
    return sequence


def cut_clip_ranges_batch(db: Session, sequence_id: str, op: CutClipRangesBatch) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip_ids = [cut.clip_id for cut in op.cuts]
    if len(clip_ids) != len(set(clip_ids)):
        raise SequenceDomainError("Each clip may only appear once in a batch cut")
    journal = Journal(db, sequence)
    for cut in op.cuts:
        _apply_clip_range_cuts(journal, cut.clip_id, cut.ranges)
    _record_operation(
        db,
        sequence,
        kind="apply_transcript_edits_batch",
        payload={"clip_ids": clip_ids, "changes": journal.entries},
        summary={"operation": "apply_transcript_edits_batch", "clips": len(clip_ids)},
        actor_id=op.actor_id,
    )
    return sequence


def _apply_clip_range_cuts(journal: Journal, clip_id: str, ranges: tuple[tuple[float, float], ...]) -> None:
    """Apply one clip's range cuts without committing or recording an operation."""

    clip = _require_clip(journal.db, journal.sequence.id, clip_id)

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

    speed = clip.speed or 1.0
    common = {
        "workspace_id": clip.workspace_id,
        "sequence_id": clip.sequence_id,
        "track_id": clip.track_id,
        "asset_id": clip.asset_id,
        **_inherited(clip),
    }
    orig_in, orig_out = clip.src_in, clip.src_out
    timeline_cursor = clip.timeline_start
    journal.delete(clip)
    for src_start, src_end in kept:
        journal.create(
            Clip(
                timeline_start=timeline_cursor,
                src_in=src_start,
                src_out=src_end,
                # 关键帧/淡变按保留段的源区间重投影(同 split);否则每段重播整段动画、并在切口淡一次。
                **{**common, **_sliced_inherited(common, orig_in, orig_out, src_start, src_end)},
            )
        )
        timeline_cursor += (src_end - src_start) / speed


@dataclass
class SplitClipPoints:
    """Split one clip into pieces at several source-time cut points, in a single op.

    Unlike cut_clip_ranges NOTHING is removed — the pieces stay at their original
    timeline positions (transcript 「按句切分」 / 单句独立成片段). Recorded as split_clip
    so the existing original+created undo/redo path applies unchanged.
    """

    clip_id: str
    src_times: tuple[float, ...]
    #: 链接组一起切(视频在这一刻切开,链接音频也在同一刻切开);False = 只切这一段。见 links.py。
    linked: bool = True
    actor_id: str | None = None


@dataclass(frozen=True)
class ClipPointSplits:
    clip_id: str
    src_times: tuple[float, ...]


@dataclass(frozen=True)
class SplitClipPointsBatch:
    """Split several clips as one user gesture and one undo step."""

    splits: tuple[ClipPointSplits, ...]
    #: 链接组一起切(视频在这一刻切开,链接音频也在同一刻切开);False = 只切这一段。见 links.py。
    linked: bool = True
    actor_id: str | None = None


def split_clip_at_points(db: Session, sequence_id: str, op: SplitClipPoints) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    journal = Journal(db, sequence)
    _apply_clip_point_splits(journal, op.clip_id, op.src_times, linked=op.linked)
    _record_operation(
        db,
        sequence,
        kind="split_clip",
        payload={"clip_id": op.clip_id, "changes": journal.entries},
        summary={"operation": "split_clip", "clip_id": op.clip_id},
        actor_id=op.actor_id,
    )
    return sequence


def split_clip_points_batch(db: Session, sequence_id: str, op: SplitClipPointsBatch) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip_ids = [split.clip_id for split in op.splits]
    if len(clip_ids) != len(set(clip_ids)):
        raise SequenceDomainError("Each clip may only appear once in a batch split")
    journal = Journal(db, sequence)
    for split in op.splits:
        _apply_clip_point_splits(journal, split.clip_id, split.src_times, linked=op.linked)
    _record_operation(
        db,
        sequence,
        kind="apply_transcript_edits_batch",
        payload={"clip_ids": clip_ids, "changes": journal.entries},
        summary={"operation": "apply_transcript_edits_batch", "clips": len(clip_ids)},
        actor_id=op.actor_id,
    )
    return sequence


def _apply_clip_point_splits(journal: Journal, clip_id: str, src_times: tuple[float, ...], *, linked: bool) -> None:
    """Apply one clip's point splits without committing or recording an operation."""

    clip = _require_clip(journal.db, journal.sequence.id, clip_id)
    # Interior points only, sorted; drop any too close to a neighbour or to the clip ends.
    points: list[float] = []
    cursor = clip.src_in
    for value in sorted({float(point) for point in src_times}):
        if value - cursor > MIN_CUT_REMAINDER and clip.src_out - value > MIN_CUT_REMAINDER:
            points.append(value)
            cursor = value
    if not points:
        raise SequenceDomainError("No valid split point inside the clip")
    # _split_into_pieces 用 _inherited(不是手写字段表):此前这里漏了 transform / muted / text_override,
    # 多点切分会把画面变换、静音、文本一并丢掉 —— 与单点切分行为不一致。
    _split_linked(journal, clip, points, linked=linked)
