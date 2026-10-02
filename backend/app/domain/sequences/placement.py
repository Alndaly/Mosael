"""片段的放置:插入、移动、修剪、删除与波纹删除。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.db.models import Asset, Clip, Sequence, Track
from app.domain.media_kinds import MEDIA_KINDS
from app.domain.sequences._timeline import (
    MIN_CUT_REMAINDER,
    _record_operation,
    _require_clip,
    _require_sequence,
    _validate_clip_range,
    require_speed,
)
from app.domain.sequences.coverage import (
    EPS,
    clear_range,
    clip_end,
    make_room,
    neighbours,
    remove_time_ranges,
)
from app.domain.sequences.errors import SequenceDomainError, SequenceNotFound
from app.domain.sequences.journal import Journal


@dataclass(frozen=True)
class InsertClip:
    track_id: str
    asset_id: str
    timeline_start: float
    src_in: float
    src_out: float
    # Insert-edit:落点后的同轨片段右移让位(与 MoveClip.ripple 同语义)。不让位就是覆盖。
    ripple: bool = False
    #: 一放下就是这个倍速。配音、旁白按它的位置定速:先按 1 倍放下再改速的话,放下那一刻多出来的
    #: 那截已经把后面的片段盖掉了。
    speed: float = 1.0
    actor_id: str | None = None


@dataclass(frozen=True)
class MoveClip:
    clip_id: str
    timeline_start: float
    track_id: str | None = None
    # Insert-edit (DaVinci "insert" mode): push destination-track clips at or
    # after the drop point right by this clip's duration to make room.
    ripple: bool = False
    actor_id: str | None = None


@dataclass(frozen=True)
class MoveClipsBatch:
    """一次手势移动多个片段(框选后整组拖动)。

    刻意不是「循环调用 move_clip」:那样 N 个片段会产生 N 条 SequenceOperation,撤销一次
    只退回一个,用户得按 N 次 ⌘Z 才能还原一次拖动。整组落成一条操作,撤销才与手势对齐。

    也不支持 ripple:插入模式为单个片段"挤开下游"是明确的,一组跨轨片段要挤开什么则没有
    唯一解。组拖一律按覆盖(overwrite)语义,与前端 startClipDrag 里的说明一致:落点盖住的
    同轨片段被裁掉或切开;组里的几段彼此叠上时,后开始的盖住先开始的。
    """

    moves: tuple["ClipMove", ...]
    actor_id: str | None = None


@dataclass(frozen=True)
class ClipMove:
    clip_id: str
    timeline_start: float
    track_id: str | None = None


@dataclass(frozen=True)
class TrimClip:
    clip_id: str
    timeline_start: float
    src_in: float
    src_out: float
    actor_id: str | None = None


@dataclass(frozen=True)
class DeleteClip:
    clip_id: str
    actor_id: str | None = None


def insert_clip(db: Session, sequence_id: str, op: InsertClip) -> Clip:
    """插入一个片段,返回**插进去的那一段**。

    此前返回整条时间线,于是调用方只能自己去猜刚插的是哪一段:「接到时间线」取整条序列里
    最新的一段(并行分支同时往上接时拿到的是别人的),字幕配音按落点在轨上找(重配同一句时
    找到的是上一次的配音)—— 变速都加错了地方。新建的东西由建它的操作说出来,不要让人猜。

    落点上已有片段时是**覆盖**(coverage.clear_range);插入模式(ripple)先把后面的推开再放。
    """
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    asset = db.get(Asset, op.asset_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceNotFound("Track not found")
    if asset is None or asset.workspace_id != sequence.workspace_id:
        raise SequenceNotFound("Asset not found")
    if asset.kind not in MEDIA_KINDS:
        #: 文档(ADR 0031)没有画面和声音可放 —— 渲染时会炸在 ffmpeg 里,在这里就说清楚。
        raise SequenceDomainError("seqErr_assetNotMedia", name=asset.name)
    _validate_clip_range(op.timeline_start, op.src_in, op.src_out)
    speed = require_speed(op.speed)

    journal = Journal(db, sequence)
    clip = journal.create(
        Clip(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            track_id=track.id,
            asset_id=asset.id,
            timeline_start=op.timeline_start,
            src_in=op.src_in,
            src_out=op.src_out,
            speed=speed,
        )
    )
    _land(journal, [clip], ripple=op.ripple)
    _record_operation(
        db,
        sequence,
        kind="insert_clip",
        payload={"clip_id": clip.id, "changes": journal.entries},
        summary={"operation": "insert_clip", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    return clip


def _land(journal: Journal, placed: list[Clip], *, ripple: bool) -> None:
    """刚放到新位置的几段,在各自的轨上站稳:插入模式先让位,然后覆盖落点上剩下的。

    **后开始的先站**:同一次放下的几段彼此叠着时(整组拖到一起),后开始的那段盖住先开始的
    那段 —— 和迁移规整老数据同一条规矩。倒过来的话,先开始的那段会把后开始的挖掉。
    """
    placed_ids = {clip.id for clip in placed}
    if ripple:
        for clip in placed:
            make_room(journal, clip.track_id, clip.timeline_start, clip_end(clip), exclude=placed_ids)
    for clip in sorted(placed, key=lambda one: one.timeline_start, reverse=True):
        if inspect(clip).was_deleted:  # 被同一次放下的、更晚开始的那段整个盖住了
            continue
        clear_range(journal, clip.track_id, clip.timeline_start, clip_end(clip), keep={clip.id})


def _target_track(db: Session, sequence_id: str, clip: Clip, track_id: str | None) -> str:
    target_track_id = track_id or clip.track_id
    if target_track_id != clip.track_id:
        target = db.get(Track, target_track_id)
        source = db.get(Track, clip.track_id)
        if target is None or target.sequence_id != sequence_id:
            raise SequenceNotFound("Target track not found")
        if source is not None and target.kind != source.kind:
            raise SequenceDomainError("Target track kind does not match clip track kind")
    return target_track_id


def move_clip(db: Session, sequence_id: str, op: MoveClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    if op.timeline_start < 0:
        raise SequenceDomainError("timeline_start must be non-negative")
    target_track_id = _target_track(db, sequence_id, clip, op.track_id)

    journal = Journal(db, sequence)
    journal.update(clip, timeline_start=float(op.timeline_start), track_id=target_track_id)
    _land(journal, [clip], ripple=op.ripple)
    _record_operation(
        db,
        sequence,
        kind="move_clip",
        payload={"clip_id": clip.id, "changes": journal.entries},
        summary={"operation": "move_clip", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    return sequence


def move_clips_batch(db: Session, sequence_id: str, op: MoveClipsBatch) -> Sequence:
    """整组移动。逐个校验后一次性记账,失败则整组不落(校验先于任何写入)。"""
    sequence = _require_sequence(db, sequence_id)
    if not op.moves:
        raise SequenceDomainError("No clips to move")

    planned: list[tuple[Clip, float, str]] = []
    for move in op.moves:
        if move.timeline_start < 0:
            raise SequenceDomainError("timeline_start must be non-negative")
        clip = _require_clip(db, sequence_id, move.clip_id)
        planned.append((clip, float(move.timeline_start), _target_track(db, sequence_id, clip, move.track_id)))

    journal = Journal(db, sequence)
    for clip, start, target_track_id in planned:
        journal.update(clip, timeline_start=start, track_id=target_track_id)
    _land(journal, [clip for clip, _, _ in planned], ripple=False)
    _record_operation(
        db,
        sequence,
        kind="move_clips_batch",
        payload={"clip_ids": [clip.id for clip, _, _ in planned], "changes": journal.entries},
        summary={"operation": "move_clips_batch", "count": len(planned)},
        actor_id=op.actor_id,
    )
    return sequence


def trim_clip(db: Session, sequence_id: str, op: TrimClip) -> Sequence:
    """修剪:改片段的起点、入点、出点。**拉进邻居时夹到邻居的边上**,不盖住它。

    修剪是在动这一段自己的边,用户没打算动邻居 —— 和放下一段(覆盖)不是一回事。夹住而不是
    报错:拖过头是手势的常态,停在边上就是用户要的结果。
    """
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    _validate_clip_range(op.timeline_start, op.src_in, op.src_out)

    speed = clip.speed or 1.0
    start, src_in, src_out = float(op.timeline_start), float(op.src_in), float(op.src_out)
    previous_end, next_start = neighbours(db, clip)
    if start < previous_end - EPS:
        pulled = previous_end - start
        start, src_in = previous_end, src_in + pulled * speed
    end = start + (src_out - src_in) / speed
    if end > next_start + EPS:
        src_out -= (end - next_start) * speed
    if src_out - src_in <= MIN_CUT_REMAINDER:
        raise SequenceDomainError("seqErr_trimNoRoom")

    journal = Journal(db, sequence)
    journal.update(clip, timeline_start=start, src_in=src_in, src_out=src_out)
    _record_operation(
        db,
        sequence,
        kind="trim_clip",
        payload={"clip_id": clip.id, "changes": journal.entries},
        summary={"operation": "trim_clip", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    return sequence


def delete_clip(db: Session, sequence_id: str, op: DeleteClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)

    journal = Journal(db, sequence)
    journal.delete(clip)
    _record_operation(
        db,
        sequence,
        kind="delete_clip",
        payload={"clip_id": op.clip_id, "changes": journal.entries},
        summary={"operation": "delete_clip", "clip_id": op.clip_id},
        actor_id=op.actor_id,
    )
    return sequence


@dataclass(frozen=True)
class DeleteClipsBatch:
    """多选后一次删除。整批一条操作,撤销一步全部找回。"""

    clip_ids: tuple[str, ...]
    actor_id: str | None = None


@dataclass(frozen=True)
class RippleDeleteClipsBatch:
    """多选后一次波纹删除(删掉并让同轨后续左移补位)。"""

    clip_ids: tuple[str, ...]
    actor_id: str | None = None


@dataclass(frozen=True)
class RippleDeleteClip:
    """Delete a clip and shift later clips on the same track left to close the gap."""

    clip_id: str
    actor_id: str | None = None


def delete_clips_batch(db: Session, sequence_id: str, op: DeleteClipsBatch) -> Sequence:
    """一次删除多个片段(多选后按 Delete)。

    与 move_clips_batch 同理:循环调 delete_clip 会落成 N 条操作,撤销一次只找回一个,
    删 5 段要按 5 次 ⌘Z。整批记一条,撤销一步全部找回。
    """
    sequence = _require_sequence(db, sequence_id)
    if not op.clip_ids:
        raise SequenceDomainError("No clips to delete")
    # 全部先解析,任一不存在就整批不删——留下删了一半的时间线比直接报错更难收拾。
    clips = [_require_clip(db, sequence_id, clip_id) for clip_id in dict.fromkeys(op.clip_ids)]
    journal = Journal(db, sequence)
    for clip in clips:
        journal.delete(clip)
    _record_operation(
        db,
        sequence,
        kind="delete_clips_batch",
        payload={"clip_ids": [clip_id for clip_id in dict.fromkeys(op.clip_ids)], "changes": journal.entries},
        summary={"operation": "delete_clips_batch", "count": len(clips)},
        actor_id=op.actor_id,
    )
    return sequence


def ripple_delete_clips_batch(db: Session, sequence_id: str, op: RippleDeleteClipsBatch) -> Sequence:
    """一次波纹删除多个片段:删掉并让同轨后续片段左移补位,整批一条操作。"""
    sequence = _require_sequence(db, sequence_id)
    if not op.clip_ids:
        raise SequenceDomainError("No clips to delete")
    clips = [_require_clip(db, sequence_id, clip_id) for clip_id in dict.fromkeys(op.clip_ids)]
    journal = Journal(db, sequence)
    _ripple_delete(journal, clips)
    _record_operation(
        db,
        sequence,
        kind="ripple_delete_clips_batch",
        payload={"clip_ids": [clip.id for clip in clips], "changes": journal.entries},
        summary={"operation": "ripple_delete_clips_batch", "count": len(clips)},
        actor_id=op.actor_id,
    )
    return sequence


def ripple_delete_clip(db: Session, sequence_id: str, op: RippleDeleteClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    journal = Journal(db, sequence)
    _ripple_delete(journal, [clip])
    _record_operation(
        db,
        sequence,
        kind="ripple_delete_clip",
        payload={"clip_id": op.clip_id, "changes": journal.entries},
        summary={"operation": "ripple_delete_clip", "clip_id": op.clip_id},
        actor_id=op.actor_id,
    )
    return sequence


def _ripple_delete(journal: Journal, clips: list[Clip]) -> None:
    """删掉这几段,并把它们占的时间从各自的轨上拿掉(后面的左移补位)。"""
    ranges: dict[str, list[tuple[float, float]]] = {}
    for clip in clips:
        ranges.setdefault(clip.track_id, []).append((clip.timeline_start, clip_end(clip)))
    for track_id, track_ranges in ranges.items():
        remove_time_ranges(journal, track_id, track_ranges)
