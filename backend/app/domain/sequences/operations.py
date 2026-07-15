from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Asset, Clip, Sequence, SequenceOperation, SequenceRevision, Track


class SequenceDomainError(ValueError):
    pass


@dataclass(frozen=True)
class InsertClip:
    track_id: str
    asset_id: str
    timeline_start: float
    src_in: float
    src_out: float
    actor_id: str | None = None


@dataclass(frozen=True)
class MoveClip:
    clip_id: str
    timeline_start: float
    track_id: str | None = None
    actor_id: str | None = None


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
        },
        summary={"operation": "move_clip", "clip_id": clip.id},
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

    payload = {
        "clip_id": clip.id,
        "track_id": clip.track_id,
        "asset_id": clip.asset_id,
        "timeline_start": clip.timeline_start,
        "src_in": clip.src_in,
        "src_out": clip.src_out,
    }
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
    sequence.revision = after
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
