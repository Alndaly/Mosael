"""轨道:增删、排序与静音/隐藏/锁定/独奏/闪避状态。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Sequence, Track
from app.domain.sequences._timeline import _clip_payload, _record_operation, _require_sequence
from app.domain.sequences.errors import SequenceDomainError, SequenceNotFound


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
    return sequence


def move_track(db: Session, sequence_id: str, op: MoveTrack) -> Sequence:
    """Reorder a track by swapping its position with the neighbour above/below — changes the
    timeline row order and (for video tracks) the compositing z-order (改视频层级)."""
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceNotFound("Track not found")
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
    return sequence


def remove_track(db: Session, sequence_id: str, op: RemoveTrack) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceNotFound("Track not found")
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
        "hidden": track.hidden,
        "solo": track.solo,
        "locked": track.locked,
        "duck": track.duck,
        #: 用途也要记:配音轨(role="dub")撤销回来要还是配音轨 —— 名字认不出它,
        #: 再配一次就会另开一条新轨,旧的那条成了一条普通轨。
        "role": track.role,
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
    return sequence


@dataclass(frozen=True)
class SetTrackState:
    track_id: str
    muted: bool | None = None
    hidden: bool | None = None
    locked: bool | None = None
    solo: bool | None = None
    duck: bool | None = None
    actor_id: str | None = None


def set_track_state(db: Session, sequence_id: str, op: SetTrackState) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    track = db.get(Track, op.track_id)
    if track is None or track.sequence_id != sequence_id:
        raise SequenceNotFound("Track not found")
    # 静音 / 独奏 / 闪避是**声音**的开关,字幕轨没有声音。独奏一条字幕轨的结果是反的:「有轨在
    # 独奏」成立,别的轨一律闭嘴 —— 预览和成片里所有声音都没了。字幕轨不显示用的是 hidden。
    if track.kind == "subtitle" and (op.muted or op.solo or op.duck):
        raise SequenceDomainError("seqErr_subtitleTrackHasNoSound")
    # 隐藏目前只对字幕轨有定义(预览和导出都只在字幕上读它);别的轨存下来也不会起作用。
    if track.kind != "subtitle" and op.hidden:
        raise SequenceDomainError("seqErr_onlySubtitleTracksHide")
    previous = {
        "muted": track.muted, "hidden": track.hidden, "locked": track.locked, "solo": track.solo, "duck": track.duck,
    }
    if op.muted is not None:
        track.muted = op.muted
    if op.hidden is not None:
        track.hidden = op.hidden
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
            "hidden": track.hidden,
            "locked": track.locked,
            "solo": track.solo,
            "duck": track.duck,
            "previous": previous,
        },
        summary={"operation": "set_track_state", "track_id": track.id},
        actor_id=op.actor_id,
    )
    return sequence
