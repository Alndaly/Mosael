"""切分与裁剪:单点/多点切分、按源时间区间剪掉(转写驱动的编辑)。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Clip, Sequence, Track
from app.domain.sequences._timeline import (
    MIN_CUT_REMAINDER,
    _inherited,
    _record_operation,
    _require_clip,
    _require_sequence,
    _sliced_inherited,
)
from app.domain.sequences.errors import SequenceDomainError
from app.domain.sequences.coverage import EPS, clip_end, remove_time_ranges
from app.domain.sequences.journal import Journal
from app.domain.sequences.links import linked_members, new_link_group


@dataclass(frozen=True)
class CutClipRange:
    """Remove a source-time range from a clip (transcript-driven edit).

    波纹删除(见 _ripple_cut):片段在区间处切开、区间拿掉,同轨后面的、链接音频、字幕跟着左移。
    贴着片段一头的就是裁掉那一头;盖住整段就整段删掉。
    """

    clip_id: str
    src_start: float
    src_end: float
    #: 链接组员(分离出去的音频)剪掉同样的时间;False = 只剪这一段。
    linked: bool = True
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
    _ripple_cut(journal, [(clip.id, ((op.src_start, op.src_end),))], linked=op.linked)
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
    """Remove several source-time ranges from one clip in a single operation (按文字剪)。

    波纹删除,见 _ripple_cut。
    """

    clip_id: str
    ranges: tuple[tuple[float, float], ...]
    linked: bool = True
    actor_id: str | None = None


@dataclass(frozen=True)
class ClipRangeCuts:
    clip_id: str
    ranges: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class CutClipRangesBatch:
    """Remove ranges from several clips as one user gesture and one undo step."""

    cuts: tuple[ClipRangeCuts, ...]
    linked: bool = True
    actor_id: str | None = None


def cut_clip_ranges(db: Session, sequence_id: str, op: CutClipRanges) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    journal = Journal(db, sequence)
    _ripple_cut(journal, [(op.clip_id, op.ranges)], linked=op.linked)
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
    _ripple_cut(journal, [(cut.clip_id, cut.ranges) for cut in op.cuts], linked=op.linked)
    _record_operation(
        db,
        sequence,
        kind="apply_transcript_edits_batch",
        payload={"clip_ids": clip_ids, "changes": journal.entries},
        summary={"operation": "apply_transcript_edits_batch", "clips": len(clip_ids)},
        actor_id=op.actor_id,
    )
    return sequence


def _ripple_cut(
    journal: Journal, cuts: list[tuple[str, tuple[tuple[float, float], ...]]], *, linked: bool
) -> None:
    """按文字剪:把片段里这几段源时间对应的**时间线时间**拿掉,真正的波纹删除。

    此前只把这一段切开、保留部分首尾相接,别的全不管 —— 审查实测:V1 剪掉 2–4 秒之后,同轨第二段
    还在 10 秒、中间留着 2 秒黑场;分离出去的音频没剪,音画错开 2 秒;字幕也都晚了 2 秒。现在这几段
    时间从下面这些轨上一起拿掉(区间里的挖掉,后面的左移补上):

    - 这一段自己的轨:同轨后面的片段左移;
    - 链接组员的轨(linked,默认):分离出去的音频剪掉同样的时间,音画仍对齐;
    - 所有未锁定的字幕轨:落在删掉区间里的字幕删掉,跨着切口的缩短,后面的跟着左移。

    别的轨(画中画、垫乐)不动:按文字剪是在剪说话的那一段,垫乐被剪出跳音比错开几秒更糟;要整条
    时间线一起拿掉某段时间,用波纹删除的 all_tracks。时间线上没有独立的「标记」,所以没有标记要挪。

    整批算一次:各段的区间先全部按**剪之前**的位置换算好,每条轨从后往前拿 —— 先拿靠前的,后面的
    区间就全错位了。
    """
    db = journal.db
    spans_by_track: dict[str, list[tuple[float, float]]] = {}
    subtitle_tracks = db.scalars(
        select(Track.id).where(
            Track.sequence_id == journal.sequence.id, Track.kind == "subtitle", Track.locked.is_(False)
        )
    ).all()
    for clip_id, ranges in cuts:
        clip = _require_clip(db, journal.sequence.id, clip_id)
        speed = clip.speed or 1.0
        spans = [
            (clip.timeline_start + (start - clip.src_in) / speed, clip.timeline_start + (end - clip.src_in) / speed)
            for start, end in _removed_source(clip, ranges)
        ]
        tracks = {clip.track_id, *(member.track_id for member in linked_members(db, [clip], linked=linked))}
        for track_id in tracks | set(subtitle_tracks):
            spans_by_track.setdefault(track_id, []).extend(spans)
    for track_id, spans in spans_by_track.items():
        remove_time_ranges(journal, track_id, spans)


def _removed_source(clip: Clip, ranges: tuple[tuple[float, float], ...]) -> list[tuple[float, float]]:
    """要拿掉的源时间区间:夹进片段、合并相邻;两段之间(或贴着片段两头)剩不到最小余量的碎片一并拿掉 ——
    留下一截不到一帧的画面,只会在成片里闪一下。"""
    clamped = sorted(
        (max(float(start), clip.src_in), min(float(end), clip.src_out))
        for start, end in ranges
        if min(float(end), clip.src_out) > max(float(start), clip.src_in)
    )
    if not clamped:
        raise SequenceDomainError("No cut range intersects the clip")
    kept: list[tuple[float, float]] = []
    cursor = clip.src_in
    for start, end in clamped:
        if start - cursor > MIN_CUT_REMAINDER:
            kept.append((cursor, start))
        cursor = max(cursor, end)
    if clip.src_out - cursor > MIN_CUT_REMAINDER:
        kept.append((cursor, clip.src_out))
    bounds = [clip.src_in, *(edge for piece in kept for edge in piece), clip.src_out]
    return [(start, end) for start, end in zip(bounds[::2], bounds[1::2]) if end > start]


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
