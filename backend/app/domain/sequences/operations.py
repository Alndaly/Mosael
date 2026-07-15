from __future__ import annotations

from dataclasses import dataclass

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


def insert_clip(db: Session, sequence_id: str, op: InsertClip) -> Sequence:
    sequence = db.get(Sequence, sequence_id)
    track = db.get(Track, op.track_id)
    asset = db.get(Asset, op.asset_id)
    if sequence is None:
        raise SequenceDomainError("Sequence not found")
    if track is None or track.sequence_id != sequence_id:
        raise SequenceDomainError("Track not found")
    if asset is None or asset.workspace_id != sequence.workspace_id:
        raise SequenceDomainError("Asset not found")
    if op.src_out <= op.src_in:
        raise SequenceDomainError("src_out must be greater than src_in")
    if op.timeline_start < 0:
        raise SequenceDomainError("timeline_start must be non-negative")

    before = sequence.revision
    after = before + 1
    clip = Clip(
        workspace_id=sequence.workspace_id,
        sequence_id=sequence.id,
        track_id=track.id,
        asset_id=asset.id,
        timeline_start=op.timeline_start,
        src_in=op.src_in,
        src_out=op.src_out,
    )
    sequence.revision = after
    db.add(clip)
    db.add(
        SequenceOperation(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            revision_before=before,
            revision_after=after,
            kind="insert_clip",
            payload={
                "track_id": op.track_id,
                "asset_id": op.asset_id,
                "timeline_start": op.timeline_start,
                "src_in": op.src_in,
                "src_out": op.src_out,
            },
            actor_id=op.actor_id,
        )
    )
    db.add(
        SequenceRevision(
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            revision=after,
            summary={"operation": "insert_clip", "clip_id": clip.id},
        )
    )
    db.commit()
    return sequence
