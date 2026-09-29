"""片段的放置:插入、移动、修剪、删除与波纹删除。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Asset, Clip, Sequence, Track
from app.domain.media_kinds import MEDIA_KINDS
from app.domain.sequences._timeline import (
    MIN_CUT_REMAINDER,
    _clip_payload,
    _inherited,
    _record_operation,
    _require_clip,
    _require_sequence,
    _validate_clip_range,
    timeline_span,
)
from app.domain.sequences.errors import SequenceDomainError, SequenceNotFound


@dataclass(frozen=True)
class InsertClip:
    track_id: str
    asset_id: str
    timeline_start: float
    src_in: float
    src_out: float
    # Insert-edit:落点后的同轨片段右移让位(与 MoveClip.ripple 同语义)。
    ripple: bool = False
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
    唯一解。组拖一律按覆盖(overwrite)语义,与前端 startClipDrag 里的说明一致。
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


def _ripple_make_room(
    db: Session, sequence: Sequence, *, track_id: str, exclude_id: str, start: float, moved_end: float
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """插入编辑让位(move/insert 共用):
    ① 落点若插进某个片段的身体里(它先于落点开始、又延伸过落点),先在落点处把它
       切开 — 原片段收尾到落点,尾段作为新片段落在落点上。不切的话尾段会被压在
       移入片段底下,"插入模式还是覆盖"就是这个洞。
    ② 落点及之后的同轨片段(含刚切出的尾段)整体右移**实际重叠量**,间距保留;
       无碰撞不动,避免轻轻一拖整条时间线炸开。
    返回 (shifted, split) 供 payload 记录撤销信息;split 为 None 表示没切。"""
    split: dict[str, Any] | None = None
    straddler = next(
        (
            c
            for c in db.scalars(select(Clip).where(Clip.track_id == track_id, Clip.id != exclude_id))
            if c.timeline_start < start - 1e-9 and c.timeline_start + timeline_span(c) > start + 1e-9
        ),
        None,
    )
    if straddler is not None:
        speed = straddler.speed or 1.0
        cut_src = straddler.src_in + (start - straddler.timeline_start) * speed
        # 与 split_clip 相同的最小余量保护:切点贴边就不切(留给重叠量右移处理)。
        if straddler.src_in + MIN_CUT_REMAINDER < cut_src < straddler.src_out - MIN_CUT_REMAINDER:
            previous_src_out = straddler.src_out
            tail = Clip(
                workspace_id=sequence.workspace_id,
                sequence_id=sequence.id,
                track_id=straddler.track_id,
                asset_id=straddler.asset_id,
                **_inherited(straddler),
                timeline_start=start,
                src_in=cut_src,
                src_out=straddler.src_out,
            )
            straddler.src_out = cut_src
            db.add(tail)
            db.flush()
            split = {"clip_id": straddler.id, "previous_src_out": previous_src_out, "tail": _clip_payload(tail)}
    downstream = list(
        db.scalars(
            select(Clip).where(
                Clip.track_id == track_id,
                Clip.id != exclude_id,
                Clip.timeline_start >= start - 1e-9,
            )
        )
    )
    shifted: list[dict[str, Any]] = []
    overlap = moved_end - min((c.timeline_start for c in downstream), default=moved_end)
    if downstream and overlap > 1e-9:
        for other in downstream:  # 同量右移 → 片段间原有间距保留
            new_start = other.timeline_start + overlap
            shifted.append(
                {"clip_id": other.id, "previous_timeline_start": other.timeline_start, "timeline_start": new_start}
            )
            other.timeline_start = new_start
    return shifted, split


def insert_clip(db: Session, sequence_id: str, op: InsertClip) -> Clip:
    """插入一个片段,返回**插进去的那一段**。

    此前返回整条时间线,于是调用方只能自己去猜刚插的是哪一段:「接到时间线」取整条序列里
    最新的一段(并行分支同时往上接时拿到的是别人的),字幕配音按落点在轨上找(重配同一句时
    找到的是上一次的配音)—— 变速都加错了地方。新建的东西由建它的操作说出来,不要让人猜。
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

    clip = Clip(
        workspace_id=sequence.workspace_id,
        sequence_id=sequence.id,
        track_id=track.id,
        asset_id=asset.id,
        timeline_start=op.timeline_start,
        src_in=op.src_in,
        src_out=op.src_out,
    )
    db.add(clip)
    db.flush()  # materialize clip.id so the operation payload can invert

    shifted: list[dict[str, Any]] = []
    split: dict[str, Any] | None = None
    if op.ripple:
        shifted, split = _ripple_make_room(
            db,
            sequence,
            track_id=track.id,
            exclude_id=clip.id,
            start=op.timeline_start,
            moved_end=op.timeline_start + timeline_span(clip),
        )

    _record_operation(
        db,
        sequence,
        kind="insert_clip",
        payload={
            "clip_id": clip.id,
            "track_id": op.track_id,
            "asset_id": op.asset_id,
            "timeline_start": op.timeline_start,
            "src_in": op.src_in,
            "src_out": op.src_out,
            "shifted": shifted,
            "split": split,
        },
        summary={"operation": "insert_clip", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return clip


def move_clip(db: Session, sequence_id: str, op: MoveClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    if op.timeline_start < 0:
        raise SequenceDomainError("timeline_start must be non-negative")

    previous_track_id = clip.track_id
    target_track_id = op.track_id or clip.track_id
    if target_track_id != clip.track_id:
        target = db.get(Track, target_track_id)
        source = db.get(Track, clip.track_id)
        if target is None or target.sequence_id != sequence_id:
            raise SequenceNotFound("Target track not found")
        if source is not None and target.kind != source.kind:
            raise SequenceDomainError("Target track kind does not match clip track kind")
        clip.track_id = target.id

    previous_start = clip.timeline_start
    clip.timeline_start = op.timeline_start

    shifted: list[dict[str, Any]] = []
    split: dict[str, Any] | None = None
    if op.ripple:
        shifted, split = _ripple_make_room(
            db,
            sequence,
            track_id=clip.track_id,
            exclude_id=clip.id,
            start=op.timeline_start,
            moved_end=op.timeline_start + timeline_span(clip),
        )

    _record_operation(
        db,
        sequence,
        kind="move_clip",
        payload={
            "clip_id": clip.id,
            "track_id": clip.track_id,
            "timeline_start": op.timeline_start,
            "previous_timeline_start": previous_start,
            "previous_track_id": previous_track_id,
            "shifted": shifted,
            "split": split,
        },
        summary={"operation": "move_clip", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    db.commit()
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
        target_track_id = move.track_id or clip.track_id
        if target_track_id != clip.track_id:
            target = db.get(Track, target_track_id)
            source = db.get(Track, clip.track_id)
            if target is None or target.sequence_id != sequence_id:
                raise SequenceNotFound("Target track not found")
            if source is not None and target.kind != source.kind:
                raise SequenceDomainError("Target track kind does not match clip track kind")
        planned.append((clip, float(move.timeline_start), target_track_id))

    moved: list[dict[str, Any]] = []
    for clip, start, target_track_id in planned:
        moved.append(
            {
                "clip_id": clip.id,
                "timeline_start": start,
                "track_id": target_track_id,
                "previous_timeline_start": clip.timeline_start,
                "previous_track_id": clip.track_id,
            }
        )
        clip.timeline_start = start
        clip.track_id = target_track_id

    _record_operation(
        db,
        sequence,
        kind="move_clips_batch",
        payload={"moved": moved},
        summary={"operation": "move_clips_batch", "count": len(moved)},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def trim_clip(db: Session, sequence_id: str, op: TrimClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    _validate_clip_range(op.timeline_start, op.src_in, op.src_out)

    previous = {
        "timeline_start": clip.timeline_start,
        "src_in": clip.src_in,
        "src_out": clip.src_out,
    }
    clip.timeline_start = op.timeline_start
    clip.src_in = op.src_in
    clip.src_out = op.src_out
    _record_operation(
        db,
        sequence,
        kind="trim_clip",
        payload={
            "clip_id": clip.id,
            "timeline_start": op.timeline_start,
            "src_in": op.src_in,
            "src_out": op.src_out,
            "previous": previous,
        },
        summary={"operation": "trim_clip", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def delete_clip(db: Session, sequence_id: str, op: DeleteClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)

    payload = _clip_payload(clip)
    db.delete(clip)
    _record_operation(
        db,
        sequence,
        kind="delete_clip",
        payload=payload,
        summary={"operation": "delete_clip", "clip_id": payload["clip_id"]},
        actor_id=op.actor_id,
    )
    db.commit()
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
    deleted = [_clip_payload(clip) for clip in clips]
    for clip in clips:
        db.delete(clip)
    _record_operation(
        db,
        sequence,
        kind="delete_clips_batch",
        payload={"deleted": deleted},
        summary={"operation": "delete_clips_batch", "count": len(deleted)},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def ripple_delete_clips_batch(db: Session, sequence_id: str, op: RippleDeleteClipsBatch) -> Sequence:
    """一次波纹删除多个片段:删掉并让同轨后续片段左移补位,整批一条操作。"""
    sequence = _require_sequence(db, sequence_id)
    if not op.clip_ids:
        raise SequenceDomainError("No clips to delete")
    clips = [_require_clip(db, sequence_id, clip_id) for clip_id in dict.fromkeys(op.clip_ids)]
    # 从后往前删:先删靠前的会把后面的目标一起左移,后续的 anchor 就全错位了。
    clips.sort(key=lambda c: c.timeline_start, reverse=True)

    entries: list[dict[str, Any]] = []
    for clip in clips:
        gap = timeline_span(clip)
        anchor = clip.timeline_start
        original = _clip_payload(clip)
        shifted: list[dict[str, Any]] = []
        followers = db.scalars(
            select(Clip).where(Clip.track_id == clip.track_id, Clip.id != clip.id, Clip.timeline_start >= anchor)
        )
        for other in followers:
            new_start = max(anchor, other.timeline_start - gap)
            if new_start == other.timeline_start:
                continue
            shifted.append(
                {"clip_id": other.id, "previous_timeline_start": other.timeline_start, "timeline_start": new_start}
            )
            other.timeline_start = new_start
        db.delete(clip)
        db.flush()  # 让下一轮的 followers 查询看到本轮的位移与删除
        entries.append({"original": original, "shifted": shifted})

    _record_operation(
        db,
        sequence,
        kind="ripple_delete_clips_batch",
        payload={"entries": entries},
        summary={"operation": "ripple_delete_clips_batch", "count": len(entries)},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def ripple_delete_clip(db: Session, sequence_id: str, op: RippleDeleteClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    gap = timeline_span(clip)
    anchor = clip.timeline_start

    original = _clip_payload(clip)
    shifted: list[dict[str, Any]] = []
    followers = db.scalars(
        select(Clip).where(Clip.track_id == clip.track_id, Clip.id != clip.id, Clip.timeline_start >= anchor)
    )
    for other in followers:
        new_start = max(anchor, other.timeline_start - gap)
        if new_start == other.timeline_start:
            continue
        shifted.append(
            {"clip_id": other.id, "previous_timeline_start": other.timeline_start, "timeline_start": new_start}
        )
        other.timeline_start = new_start
    db.delete(clip)
    _record_operation(
        db,
        sequence,
        kind="ripple_delete_clip",
        payload={"clip_id": original["clip_id"], "original": original, "shifted": shifted},
        summary={"operation": "ripple_delete_clip", "clip_id": original["clip_id"], "shifted": len(shifted)},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence
