from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.db.models import Asset, Clip, Sequence, SequenceOperation, SequenceRevision, Track
from app.domain.sequences.errors import SequenceDomainError


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


def insert_clip(db: Session, sequence_id: str, op: InsertClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    asset = db.get(Asset, op.asset_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceDomainError("Track not found")
    if asset is None or asset.workspace_id != sequence.workspace_id:
        raise SequenceDomainError("Asset not found")
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
    return sequence


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
            raise SequenceDomainError("Target track not found")
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
                raise SequenceDomainError("Target track not found")
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


@dataclass(frozen=True)
class AddTrack:
    kind: str  # "video" | "audio"
    actor_id: str | None = None


@dataclass(frozen=True)
class RemoveTrack:
    track_id: str
    #: Deleting a track that still holds clips destroys them, so it is refused unless the
    #: caller says so explicitly — the UI asks first and names the count.
    with_clips: bool = False
    actor_id: str | None = None


@dataclass(frozen=True)
class MoveTrack:
    track_id: str
    direction: str  # "up" | "down"
    actor_id: str | None = None


@dataclass(frozen=True)
class SetClipEffects:
    clip_id: str
    effects: dict[str, Any]
    actor_id: str | None = None


def add_track(db: Session, sequence_id: str, op: AddTrack) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    if op.kind not in ("video", "audio", "subtitle"):
        raise SequenceDomainError("Track kind must be video, audio, or subtitle")
    existing = [track for track in sequence.tracks if track.kind == op.kind]
    prefix = {"video": "V", "audio": "A", "subtitle": "S"}[op.kind]
    track = Track(
        sequence_id=sequence.id,
        kind=op.kind,
        name=f"{prefix}{len(existing) + 1}",
        position=max((item.position for item in sequence.tracks), default=-1) + 1,
    )
    db.add(track)
    db.flush()
    _record_operation(
        db,
        sequence,
        kind="add_track",
        payload={"track_id": track.id, "kind": track.kind, "name": track.name, "position": track.position},
        summary={"operation": "add_track", "track_id": track.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def move_track(db: Session, sequence_id: str, op: MoveTrack) -> Sequence:
    """Reorder a track by swapping its position with the neighbour above/below — changes the
    timeline row order and (for video tracks) the compositing z-order (改视频层级)."""
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceDomainError("Track not found")
    ordered = sorted(sequence.tracks, key=lambda item: item.position)
    index = next(i for i, item in enumerate(ordered) if item.id == track.id)
    swap = index - 1 if op.direction == "up" else index + 1
    if swap < 0 or swap >= len(ordered):
        return sequence  # already at the edge — no-op
    other = ordered[swap]
    track_prev, other_prev = track.position, other.position
    track.position, other.position = other_prev, track_prev
    _record_operation(
        db,
        sequence,
        kind="move_track",
        payload={"track_id": track.id, "track_prev": track_prev, "other_id": other.id, "other_prev": other_prev},
        summary={"operation": "move_track", "track_id": track.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def remove_track(db: Session, sequence_id: str, op: RemoveTrack) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceDomainError("Track not found")
    if track.clips and not op.with_clips:
        raise SequenceDomainError("Track must be empty before it can be removed")
    # Record the clips as well as the track: without them undo would hand back an empty track
    # and the footage on it would be gone for good.
    payload = {
        "track_id": track.id,
        "kind": track.kind,
        "name": track.name,
        "position": track.position,
        "muted": track.muted,
        "solo": track.solo,
        "locked": track.locked,
        "duck": track.duck,
        "clips": [_clip_payload(clip) for clip in track.clips],
    }
    for clip in list(track.clips):
        db.delete(clip)
    db.delete(track)
    _record_operation(
        db,
        sequence,
        kind="remove_track",
        payload=payload,
        summary={
            "operation": "remove_track",
            "track_id": payload["track_id"],
            "clips": len(payload["clips"]),
        },
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


@dataclass(frozen=True)
class InsertTextClip:
    """A subtitle/text clip: no asset, text lives in text_override."""

    track_id: str
    text: str
    timeline_start: float
    duration: float
    actor_id: str | None = None


@dataclass(frozen=True)
class GenerateSubtitles:
    """Batch-insert many subtitle cues onto one subtitle track in a single op (一键生成字幕
    from the transcript). cues = tuple of (text, timeline_start, duration)."""

    track_id: str
    cues: tuple[tuple[str, float, float], ...]
    actor_id: str | None = None


def generate_subtitles(db: Session, sequence_id: str, op: GenerateSubtitles) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceDomainError("Track not found")
    if track.kind != "subtitle":
        raise SequenceDomainError("Subtitles need a subtitle track")
    created: list[dict[str, Any]] = []
    seen: set[tuple[float, str]] = set()
    for text, start, duration in op.cues:
        cleaned = (text or "").strip()
        if not cleaned or duration <= 0 or start < 0:
            continue
        # Drop exact duplicate cues (same start + text) — projectTranscript emits a segment
        # once per clip that references its asset, so a reused/overlapping clip would otherwise
        # insert every subtitle twice.
        key = (round(float(start), 3), cleaned)
        if key in seen:
            continue
        seen.add(key)
        clip = Clip(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            track_id=track.id,
            asset_id=None,
            timeline_start=float(start),
            src_in=0,
            src_out=float(duration),
            text_override=cleaned,
        )
        db.add(clip)
        db.flush()
        created.append(_clip_payload(clip))
    if not created:
        raise SequenceDomainError("No subtitle cues to insert")
    _record_operation(
        db,
        sequence,
        kind="insert_clips_batch",
        payload={"created": created},
        summary={"operation": "insert_clips_batch", "count": len(created)},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def insert_text_clip(db: Session, sequence_id: str, op: InsertTextClip) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceDomainError("Track not found")
    # 字幕轨 = 序列级统一样式的底部字幕;video 轨 = 花字(每条自带样式、transform 定位)。
    if track.kind not in ("subtitle", "video"):
        raise SequenceDomainError("Text clips can only be placed on subtitle or video tracks")
    if not op.text.strip():
        raise SequenceDomainError("Text must not be empty")
    if op.duration <= 0:
        raise SequenceDomainError("Duration must be positive")
    _validate_clip_range(op.timeline_start, 0, op.duration)

    clip = Clip(
        workspace_id=sequence.workspace_id,
        sequence_id=sequence.id,
        track_id=track.id,
        asset_id=None,
        timeline_start=op.timeline_start,
        src_in=0,
        src_out=op.duration,
        text_override=op.text,
    )
    db.add(clip)
    db.flush()
    _record_operation(
        db,
        sequence,
        kind="insert_clip",
        payload=_clip_payload(clip),
        summary={"operation": "insert_clip", "clip_id": clip.id, "text": True},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


@dataclass(frozen=True)
class SetClipText:
    clip_id: str
    text: str
    actor_id: str | None = None


def set_clip_text(db: Session, sequence_id: str, op: SetClipText) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    if not op.text.strip():
        raise SequenceDomainError("Text must not be empty")
    previous = clip.text_override
    clip.text_override = op.text
    _record_operation(
        db,
        sequence,
        kind="set_clip_text",
        payload={"clip_id": clip.id, "text": op.text, "previous": previous},
        summary={"operation": "set_clip_text", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


@dataclass(frozen=True)
class SetClipTextsBatch:
    """Retext many clips as ONE operation. Translating a track clip-by-clip produced N requests,
    N revisions and N undo steps, and a failure partway through left the track half-translated
    with no single point to revert to."""

    texts: tuple[tuple[str, str], ...]  # (clip_id, text)
    actor_id: str | None = None


def set_clip_texts_batch(db: Session, sequence_id: str, op: SetClipTextsBatch) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    if not op.texts:
        raise SequenceDomainError("No texts to apply")
    entries = []
    for clip_id, text in op.texts:
        clip = _require_clip(db, sequence_id, clip_id)
        if not text.strip():
            raise SequenceDomainError("Text must not be empty")
        entries.append({"clip_id": clip.id, "text": text, "previous": clip.text_override})
    # Validate every clip BEFORE mutating any: a bad id halfway through would otherwise leave
    # the track partly rewritten, which is the exact failure this operation exists to remove.
    for entry in entries:
        _require_clip(db, sequence_id, entry["clip_id"]).text_override = entry["text"]
    _record_operation(
        db,
        sequence,
        kind="set_clip_texts_batch",
        payload={"entries": entries},
        summary={"operation": "set_clip_texts_batch", "count": len(entries)},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


@dataclass(frozen=True)
class SetClipSpeed:
    clip_id: str
    speed: float
    actor_id: str | None = None


def set_clip_speed(db: Session, sequence_id: str, op: SetClipSpeed) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    if not (0.25 <= op.speed <= 4.0):
        raise SequenceDomainError("Speed must be between 0.25 and 4")
    previous = clip.speed
    clip.speed = op.speed
    _record_operation(
        db,
        sequence,
        kind="set_clip_speed",
        payload={"clip_id": clip.id, "speed": op.speed, "previous": previous},
        summary={"operation": "set_clip_speed", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


@dataclass(frozen=True)
class SetClipGain:
    clip_id: str
    gain: float
    muted: bool
    actor_id: str | None = None


def set_clip_gain(db: Session, sequence_id: str, op: SetClipGain) -> Sequence:
    """A clip's own audio level/mute (a video clip carries its audio, like PR/DaVinci)."""
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    gain = max(0.0, min(4.0, float(op.gain)))
    previous = {"gain": clip.gain, "muted": clip.muted}
    clip.gain = gain
    clip.muted = bool(op.muted)
    _record_operation(
        db,
        sequence,
        kind="set_clip_gain",
        payload={"clip_id": clip.id, "gain": gain, "muted": bool(op.muted), "previous": previous},
        summary={"operation": "set_clip_gain", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


@dataclass(frozen=True)
class DetachClipAudio:
    clip_id: str
    actor_id: str | None = None


def _range_free(track: Track, start: float, end: float) -> bool:
    for other in track.clips:
        other_end = other.timeline_start + timeline_span(other)
        if start < other_end - 1e-6 and other.timeline_start < end - 1e-6:
            return False
    return True


def detach_clip_audio(db: Session, sequence_id: str, op: DetachClipAudio) -> Sequence:
    """Split a video clip's audio onto an audio track (PR/DaVinci 分离音频): copy the clip's
    audio to the first free audio track (creating one if needed) and mute the video clip so the
    audio isn't doubled. The detached audio inherits the clip's speed/gain."""
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    track = db.get(Track, clip.track_id)
    if track is None or track.kind != "video":
        raise SequenceDomainError("只能从视频片段分离音频")
    if not clip.asset_id:
        raise SequenceDomainError("该片段没有音频源")
    duration = timeline_span(clip)
    start, end = clip.timeline_start, clip.timeline_start + duration

    audio_tracks = sorted((t for t in sequence.tracks if t.kind == "audio"), key=lambda t: t.position)
    target = next((t for t in audio_tracks if _range_free(t, start, end)), None)
    created_track = None
    if target is None:
        target = Track(
            sequence_id=sequence.id,
            kind="audio",
            name=f"A{len(audio_tracks) + 1}",
            position=max((t.position for t in sequence.tracks), default=-1) + 1,
        )
        db.add(target)
        db.flush()
        created_track = {"id": target.id, "name": target.name, "position": target.position}

    audio_clip = Clip(
        workspace_id=sequence.workspace_id,
        sequence_id=sequence.id,
        track_id=target.id,
        asset_id=clip.asset_id,
        timeline_start=clip.timeline_start,
        src_in=clip.src_in,
        src_out=clip.src_out,
        speed=clip.speed,
        gain=clip.gain,
    )
    db.add(audio_clip)
    db.flush()
    video_muted_prev = clip.muted
    clip.muted = True

    _record_operation(
        db,
        sequence,
        kind="detach_clip_audio",
        payload={
            "video_clip_id": clip.id,
            "video_muted_prev": video_muted_prev,
            "created_track": created_track,
            "audio_clip": {
                "id": audio_clip.id,
                "track_id": target.id,
                "asset_id": clip.asset_id,
                "timeline_start": clip.timeline_start,
                "src_in": clip.src_in,
                "src_out": clip.src_out,
                "speed": clip.speed,
                "gain": clip.gain,
            },
        },
        summary={"operation": "detach_clip_audio", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


def set_clip_effects(db: Session, sequence_id: str, op: SetClipEffects) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    previous = dict(clip.effects or {})
    clip.effects = op.effects
    _record_operation(
        db,
        sequence,
        kind="set_clip_effect",
        payload={"clip_id": clip.id, "effects": op.effects, "previous": previous},
        summary={"operation": "set_clip_effect", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


_TRANSFORM_DEFAULTS: dict[str, float] = {"scale": 1.0, "x": 0.0, "y": 0.0, "rotation": 0.0, "opacity": 1.0}
_TRANSFORM_BOUNDS: dict[str, tuple[float, float]] = {
    "scale": (0.1, 4.0),
    "x": (-2.0, 2.0),
    "y": (-2.0, 2.0),
    "rotation": (-180.0, 180.0),
    "opacity": (0.0, 1.0),
}


def _clean_keyframes(raw: Any) -> list[dict[str, float]]:
    """清洗关键帧轨:每点 t 钳到 [0,1],各属性按 transform 范围钳制,丢弃空点,按 t 升序。

    每个属性独立成轨——一个点只携带它打了的属性,缺的属性从静态基值取。非 dict 的点、t 缺失
    或非数字的点直接剔除;某属性值非数字则跳过该属性。存下来的形态与 render_plan 侧的读取语义
    一致,保证「打了就能导出、导出即所见」。"""
    if not isinstance(raw, list):
        return []
    cleaned: list[dict[str, float]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            t = float(item["t"])
        except (KeyError, TypeError, ValueError):
            continue
        point: dict[str, float] = {"t": max(0.0, min(1.0, t))}
        for key, (lo, hi) in _TRANSFORM_BOUNDS.items():
            if key not in item:
                continue
            try:
                value = float(item[key])
            except (TypeError, ValueError):
                continue
            point[key] = max(lo, min(hi, value))
        if len(point) > 1:  # 除 t 外至少携带一个属性,才是有效关键帧
            cleaned.append(point)
    cleaned.sort(key=lambda p: p["t"])
    return cleaned


def clean_transform(raw: dict[str, Any]) -> dict[str, Any]:
    """归一化片段变换:补默认、转 float、按范围钳制;保留并清洗关键帧轨。"""
    out: dict[str, Any] = {}
    for key, default in _TRANSFORM_DEFAULTS.items():
        try:
            value = float(raw.get(key, default))
        except (TypeError, ValueError) as exc:
            raise SequenceDomainError(f"transform.{key} 必须是数字") from exc
        lo, hi = _TRANSFORM_BOUNDS[key]
        out[key] = max(lo, min(hi, value))
    keyframes = _clean_keyframes(raw.get("keyframes"))
    if keyframes:
        out["keyframes"] = keyframes
    return out


@dataclass(frozen=True)
class SetClipTransform:
    clip_id: str
    transform: dict[str, Any]
    actor_id: str | None = None


def set_clip_transform(db: Session, sequence_id: str, op: SetClipTransform) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    previous = dict(clip.transform or {})
    clip.transform = clean_transform(op.transform)
    _record_operation(
        db,
        sequence,
        kind="set_clip_transform",
        payload={"clip_id": clip.id, "transform": clip.transform, "previous": previous},
        summary={"operation": "set_clip_transform", "clip_id": clip.id},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


_FILL_MODES = ("cover", "contain", "blur")


@dataclass(frozen=True)
class SetSequenceReframe:
    width: int
    height: int
    fill_mode: str = "cover"
    actor_id: str | None = None


def set_sequence_reframe(db: Session, sequence_id: str, op: SetSequenceReframe) -> Sequence:
    """改画幅(横转竖等):改序列输出宽高 + 填充模式。"""
    sequence = _require_sequence(db, sequence_id)
    if not (16 <= op.width <= 8192 and 16 <= op.height <= 8192):
        raise SequenceDomainError("画幅尺寸需在 16–8192 之间")
    fill_mode = op.fill_mode if op.fill_mode in _FILL_MODES else "cover"
    previous = {"width": sequence.width, "height": sequence.height, "reframe": dict(sequence.reframe or {})}
    sequence.width = int(op.width)
    sequence.height = int(op.height)
    sequence.reframe = {"fill_mode": fill_mode}
    _record_operation(
        db,
        sequence,
        kind="set_sequence_reframe",
        payload={"width": sequence.width, "height": sequence.height, "reframe": sequence.reframe, "previous": previous},
        summary={"operation": "set_sequence_reframe"},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


_SUBTITLE_POSITIONS = ("bottom", "center", "top")
_SUBTITLE_DEFAULTS: dict[str, Any] = {
    "font_size": 32.0,
    "color": "#ffffff",
    "bg_color": "#000000",
    "bg_opacity": 0.5,
    "bold": True,
    "position": "bottom",
    "offset": 8.0,  # % of frame height from the edge (or from center for position=center)
    "show_speaker": False,
    "font_family": "",
    "font_id": "",
}


def clean_subtitle_style(raw: dict[str, Any]) -> dict[str, Any]:
    """归一化字幕样式:补默认、钳制范围、白名单枚举(参考前身项目 SubtitleStyle)。"""
    raw = raw or {}

    def num(key: str, lo: float, hi: float) -> float:
        try:
            return max(lo, min(hi, float(raw.get(key, _SUBTITLE_DEFAULTS[key]))))
        except (TypeError, ValueError):
            return float(_SUBTITLE_DEFAULTS[key])

    position = raw.get("position", "bottom")
    return {
        "font_size": num("font_size", 10, 160),
        "color": str(raw.get("color", "#ffffff"))[:9],
        "bg_color": str(raw.get("bg_color", "#000000"))[:9],
        "bg_opacity": num("bg_opacity", 0, 1),
        "bold": bool(raw.get("bold", True)),
        "position": position if position in _SUBTITLE_POSITIONS else "bottom",
        "offset": num("offset", 0, 45),
        "show_speaker": bool(raw.get("show_speaker", False)),
        # A CSS stack for the preview; export narrows it to the one family libass accepts.
        "font_family": str(raw.get("font_family", "") or "")[:200],
        # Set only when the family comes from an uploaded font — export needs the id to find
        # the file, since an uploaded face is not installed on the rendering machine.
        "font_id": str(raw.get("font_id", "") or "")[:64],
    }


@dataclass(frozen=True)
class SetSubtitleStyle:
    style: dict[str, Any]
    actor_id: str | None = None


def set_subtitle_style(db: Session, sequence_id: str, op: SetSubtitleStyle) -> Sequence:
    """字幕全局样式(字号/颜色/背景/位置等),存在序列上。"""
    sequence = _require_sequence(db, sequence_id)
    previous = dict(sequence.subtitle_style or {})
    sequence.subtitle_style = clean_subtitle_style(op.style)
    _record_operation(
        db,
        sequence,
        kind="set_subtitle_style",
        payload={"style": sequence.subtitle_style, "previous": previous},
        summary={"operation": "set_subtitle_style"},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


@dataclass(frozen=True)
class SplitClip:
    """Cut a clip into two at a source-time point — nothing is removed."""

    clip_id: str
    src_time: float
    actor_id: str | None = None


@dataclass(frozen=True)
class SetTrackState:
    track_id: str
    muted: bool | None = None
    locked: bool | None = None
    solo: bool | None = None
    duck: bool | None = None
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


def set_track_state(db: Session, sequence_id: str, op: SetTrackState) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceDomainError("Track not found")
    previous = {"muted": track.muted, "locked": track.locked, "solo": track.solo, "duck": track.duck}
    if op.muted is not None:
        track.muted = op.muted
    if op.locked is not None:
        track.locked = op.locked
    if op.solo is not None:
        track.solo = op.solo
    if op.duck is not None:
        track.duck = op.duck
    _record_operation(
        db,
        sequence,
        kind="set_track_state",
        payload={
            "track_id": track.id,
            "muted": track.muted,
            "locked": track.locked,
            "solo": track.solo,
            "duck": track.duck,
            "previous": previous,
        },
        summary={"operation": "set_track_state", "track_id": track.id},
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


def cut_clip_ranges(db: Session, sequence_id: str, op: CutClipRanges) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)

    clamped = sorted(
        (max(float(start), clip.src_in), min(float(end), clip.src_out))
        for start, end in op.ranges
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

    _record_operation(
        db,
        sequence,
        kind="apply_transcript_edit",
        payload={
            "clip_id": original["clip_id"],
            "ranges": [[start, end] for start, end in merged],
            "original": original,
            "created": created,
        },
        summary={"operation": "apply_transcript_edit", "clip_id": original["clip_id"], "created": len(created)},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


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


def split_clip_at_points(db: Session, sequence_id: str, op: SplitClipPoints) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    clip = _require_clip(db, sequence_id, op.clip_id)
    speed = clip.speed or 1

    # Interior points only, sorted; drop any too close to a neighbour or to the clip ends.
    points: list[float] = []
    cursor = clip.src_in
    for value in sorted({float(p) for p in op.src_times}):
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

    _record_operation(
        db,
        sequence,
        kind="split_clip",
        payload={"clip_id": original["clip_id"], "src_time": points[0], "original": original, "created": created},
        summary={"operation": "split_clip", "clip_id": original["clip_id"], "created": len(created)},
        actor_id=op.actor_id,
    )
    db.commit()
    return sequence


MIN_CUT_REMAINDER = 0.05


def _clip_payload(clip: Clip) -> dict[str, Any]:
    payload = {
        "clip_id": clip.id,
        "track_id": clip.track_id,
        "asset_id": clip.asset_id,
        "timeline_start": clip.timeline_start,
        "src_in": clip.src_in,
        "src_out": clip.src_out,
    }
    for field in RESTORABLE_CLIP_FIELDS:
        payload[field] = getattr(clip, field)
    return payload


#: Everything about a clip beyond where it sits. Recorded on every operation that may have to
#: rebuild the clip later, because none of it can be recovered from anywhere else — undoing a
#: delete used to hand back a clip at 1x, unity gain, unmuted and ungraded, and a subtitle with
#: no text at all. Read back with .get() and a default so operations recorded before this
#: existed still replay.
RESTORABLE_CLIP_FIELDS = ("speed", "gain", "muted", "linked_clip_id", "effects", "transform", "text_override")

#: What a piece carved out of a clip inherits. A half is still the same footage at the same
#: speed with the same grade, and half a caption still says what the caption said — rebuilding a
#: piece from position alone reset all of it. linked_clip_id is excluded: that pairs two specific
#: rows, and the pieces are new rows.
INHERITED_CLIP_FIELDS = ("speed", "gain", "muted", "effects", "transform", "text_override")


def _inherited(clip: Clip) -> dict[str, Any]:
    return {field: getattr(clip, field) for field in INHERITED_CLIP_FIELDS}


_KEYFRAME_PROPS = ("scale", "x", "y", "opacity", "rotation")


def _sample_keyframe_track(points: list[tuple[float, float]], t: float) -> float:
    """分段线性 + 端点保持 —— 与前端 sampleProp、导出端 _kf_sample 同语义。"""
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    for (t0, v0), (t1, v1) in zip(points, points[1:]):
        if t0 <= t <= t1:
            factor = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
            return v0 + (v1 - v0) * factor
    return points[-1][1]


def _slice_keyframes(
    raw: Any, props: tuple[str, ...], orig_in: float, orig_out: float, piece_in: float, piece_out: float
) -> list[dict[str, Any]] | None:
    """关键帧列表 → 裁到 [piece_in, piece_out] 后的列表;无可切内容时返回 None。

    关键帧的 t 是**片段内归一化进度**(0=片段头、1=片段尾)。按源时间把动画重投影到新片段的
    进度轴:段首/段尾取原动画在该处的采样值(跨切点连续、接得上),中间落在本段内的关键帧
    按比例重映射。
    """
    if not isinstance(raw, list) or not raw:
        return None
    span = orig_out - orig_in
    piece_span = piece_out - piece_in
    if span <= 0 or piece_span <= 0:
        return None

    sliced: list[dict[str, Any]] = []
    for prop in props:
        points = sorted(
            (float(kf["t"]), float(kf[prop]))
            for kf in raw
            if isinstance(kf, dict)
            and isinstance(kf.get("t"), (int, float))
            and isinstance(kf.get(prop), (int, float))
        )
        if not points:
            continue
        values: dict[float, float] = {}
        # 两端必取:它们承接上一段的结尾 / 下一段的开头。
        for edge_q, edge_src in ((0.0, piece_in), (1.0, piece_out)):
            values[edge_q] = _sample_keyframe_track(points, (edge_src - orig_in) / span)
        for progress, value in points:
            q = (orig_in + progress * span - piece_in) / piece_span
            if 1e-6 < q < 1 - 1e-6:
                values[round(q, 6)] = value
        sliced.extend({"t": q, prop: values[q]} for q in sorted(values))
    return sliced or None


def _sliced_transform(
    transform: Any, orig_in: float, orig_out: float, piece_in: float, piece_out: float
) -> Any:
    """画面变换(位置/缩放/旋转/透明度)动画裁到某一段;无关键帧则原样返回。

    不裁的话每段都会从头重播整段动画 —— 用户看到的是"切一刀,画面在切点跳回动画起点"。
    """
    if not isinstance(transform, dict):
        return transform
    sliced = _slice_keyframes(transform.get("keyframes"), _KEYFRAME_PROPS, orig_in, orig_out, piece_in, piece_out)
    return transform if sliced is None else {**transform, "keyframes": sliced}


def _sliced_effects(
    effects: Any, orig_in: float, orig_out: float, piece_in: float, piece_out: float
) -> Any:
    """effects 里同样按片段计时的东西,也要跟着切:

    · **音量关键帧**(gain_keyframes)与 transform 关键帧同构(t 为片段内进度)——不裁则每段
      重播整条音量曲线。
    · **淡入淡出**(fade_in/out、video_fade_in/out)是相对片段首尾的绝对秒数。原样复制会让
      每一段都在自己的首尾淡一次 —— 切一刀,切点处画面黑一下、声音断一下(段落切换处的
      "黑屏/断音"多半来源于此)。淡入只属于**首段**、淡出只属于**末段**,中间的切点不该有。
    """
    if not isinstance(effects, dict):
        return effects
    updated = dict(effects)
    sliced = _slice_keyframes(effects.get("gain_keyframes"), ("gain",), orig_in, orig_out, piece_in, piece_out)
    if sliced is not None:
        updated["gain_keyframes"] = sliced
    epsilon = 1e-6
    if piece_in > orig_in + epsilon:  # 不是首段 → 不该再淡入
        for key in ("fade_in", "video_fade_in"):
            if updated.get(key):
                updated[key] = 0.0
    if piece_out < orig_out - epsilon:  # 不是末段 → 不该在切点淡出
        for key in ("fade_out", "video_fade_out"):
            if updated.get(key):
                updated[key] = 0.0
    return updated


def _sliced_inherited(
    inherited: dict[str, Any], orig_in: float, orig_out: float, piece_in: float, piece_out: float
) -> dict[str, Any]:
    """切分出的一段应继承的字段:transform / effects 里按片段计时的部分都投影到该段。"""
    return {
        **inherited,
        "transform": _sliced_transform(inherited.get("transform"), orig_in, orig_out, piece_in, piece_out),
        "effects": _sliced_effects(inherited.get("effects"), orig_in, orig_out, piece_in, piece_out),
    }


def timeline_span(clip: Clip) -> float:
    """How long the clip occupies the TIMELINE. src_out - src_in is a duration in SOURCE time;
    at 2x that footage takes half as long to play. Confusing the two put split/cut pieces and
    ripple-shifted followers at the wrong times and let them overwrite their neighbours."""
    return (clip.src_out - clip.src_in) / (clip.speed or 1.0)


def _require_sequence(db: Session, sequence_id: str) -> Sequence:
    sequence = db.get(Sequence, sequence_id)
    if sequence is None:
        raise SequenceDomainError("Sequence not found")
    return sequence


def _require_clip(db: Session, sequence_id: str, clip_id: str) -> Clip:
    clip = db.get(Clip, clip_id)
    if clip is None or clip.sequence_id != sequence_id:
        raise SequenceDomainError("Clip not found")
    return clip


def _validate_clip_range(timeline_start: float, src_in: float, src_out: float) -> None:
    if timeline_start < 0:
        raise SequenceDomainError("timeline_start must be non-negative")
    if src_in < 0:
        raise SequenceDomainError("src_in must be non-negative")
    if src_out <= src_in:
        raise SequenceDomainError("src_out must be greater than src_in")


def _record_operation(
    db: Session,
    sequence: Sequence,
    *,
    kind: str,
    payload: dict[str, Any],
    summary: dict[str, Any],
    actor_id: str | None,
    undo_of: str | None = None,
) -> None:
    before = sequence.revision
    after = before + 1
    # 版本号自增走**条件 UPDATE**,不是读出来加一再写回去。
    #
    # 后者是 check-then-act:两个写入方都读到 5,都写 6,于是两条编辑共用一个版本号 —— 而
    # 版本号是撤销栈排序的依据(revision_after)、也是序列 JSON 缓存的键,两处都会因此错乱。
    # 让数据库来挑赢家,输的那个改动 0 行,当场知道自己晚了一步。
    #
    # 这条路径以前基本只有一个人在走,现在不是了:智能体批准一张确认卡就会改时间线,而用户
    # 同时还在拖片段 —— 两个写入方同时存在已经是常态。
    # (和 domain/agent/confirmations.py 的 _claim 同一个手法。)
    claimed = db.execute(
        update(Sequence).where(Sequence.id == sequence.id, Sequence.revision == before).values(revision=after)
    ).rowcount
    if claimed == 0:
        raise SequenceDomainError("这个序列刚被改过,请刷新后重试")
    db.add(
        SequenceOperation(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            revision_before=before,
            revision_after=after,
            kind=kind,
            payload=payload,
            actor_id=actor_id,
            undo_of=undo_of,
        )
    )
    db.add(
        SequenceRevision(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            revision=after,
            summary=summary,
        )
    )
