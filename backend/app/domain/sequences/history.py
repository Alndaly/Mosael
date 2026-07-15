from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Clip, Sequence, SequenceOperation
from app.domain.sequences.operations import SequenceDomainError, _record_operation, _require_sequence

"""
Undo/redo over the SequenceOperation log (plan §10.2).

Model: edit operations are appended forever. Undo applies an operation's
inverse, marks it reverted, and appends an "undo" op; redo re-applies the
original, un-reverts it, and appends a "redo" op. A fresh edit after an undo
invalidates the redo stack (checked by revision ordering).
"""

UNDOABLE_KINDS = ("insert_clip", "move_clip", "trim_clip", "delete_clip", "apply_transcript_edit")


def undo(db: Session, sequence_id: str) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    operation = _latest_undoable(db, sequence_id)
    if operation is None:
        raise SequenceDomainError("Nothing to undo")
    _apply_inverse(db, sequence, operation)
    operation.reverted = True
    _record_operation(
        db,
        sequence,
        kind="undo",
        payload={"undo_of": operation.id, "undone_kind": operation.kind},
        summary={"operation": "undo", "undone_kind": operation.kind},
        actor_id=None,
        undo_of=operation.id,
    )
    db.commit()
    return sequence


def redo(db: Session, sequence_id: str) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    undo_operation = _latest_active_undo(db, sequence_id)
    if undo_operation is None or _has_edit_after(db, sequence_id, undo_operation.revision_after):
        raise SequenceDomainError("Nothing to redo")
    original = db.get(SequenceOperation, undo_operation.undo_of or "")
    if original is None:
        raise SequenceDomainError("Nothing to redo")
    _apply_forward(db, sequence, original)
    original.reverted = False
    undo_operation.reverted = True
    _record_operation(
        db,
        sequence,
        kind="redo",
        payload={"redo_of": original.id, "redone_kind": original.kind},
        summary={"operation": "redo", "redone_kind": original.kind},
        actor_id=None,
        undo_of=undo_operation.id,
    )
    db.commit()
    return sequence


def can_undo(db: Session, sequence_id: str) -> bool:
    return _latest_undoable(db, sequence_id) is not None


def can_redo(db: Session, sequence_id: str) -> bool:
    undo_operation = _latest_active_undo(db, sequence_id)
    return undo_operation is not None and not _has_edit_after(db, sequence_id, undo_operation.revision_after)


def _latest_undoable(db: Session, sequence_id: str) -> SequenceOperation | None:
    return db.scalar(
        select(SequenceOperation)
        .where(
            SequenceOperation.sequence_id == sequence_id,
            SequenceOperation.kind.in_(UNDOABLE_KINDS),
            SequenceOperation.reverted.is_(False),
        )
        .order_by(SequenceOperation.revision_after.desc())
        .limit(1)
    )


def _latest_active_undo(db: Session, sequence_id: str) -> SequenceOperation | None:
    return db.scalar(
        select(SequenceOperation)
        .where(
            SequenceOperation.sequence_id == sequence_id,
            SequenceOperation.kind == "undo",
            SequenceOperation.reverted.is_(False),
        )
        .order_by(SequenceOperation.revision_after.desc())
        .limit(1)
    )


def _has_edit_after(db: Session, sequence_id: str, revision: int) -> bool:
    newer = db.scalar(
        select(SequenceOperation.id)
        .where(
            SequenceOperation.sequence_id == sequence_id,
            SequenceOperation.kind.in_(UNDOABLE_KINDS),
            SequenceOperation.revision_after > revision,
        )
        .limit(1)
    )
    return newer is not None


def _apply_inverse(db: Session, sequence: Sequence, operation: SequenceOperation) -> None:
    payload = operation.payload
    if operation.kind == "insert_clip":
        _delete_clip_row(db, payload["clip_id"])
    elif operation.kind == "delete_clip":
        _restore_clip_row(db, sequence, payload)
    elif operation.kind == "move_clip":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.timeline_start = payload["previous_timeline_start"]
        clip.track_id = payload.get("previous_track_id", clip.track_id)
    elif operation.kind == "trim_clip":
        clip = _require_clip_row(db, payload["clip_id"])
        previous = payload["previous"]
        clip.timeline_start = previous["timeline_start"]
        clip.src_in = previous["src_in"]
        clip.src_out = previous["src_out"]
    elif operation.kind == "apply_transcript_edit":
        for created in payload["created"]:
            _delete_clip_row(db, created["clip_id"])
        _restore_clip_row(db, sequence, payload["original"])
    else:
        raise SequenceDomainError(f"Operation {operation.kind} cannot be undone")


def _apply_forward(db: Session, sequence: Sequence, operation: SequenceOperation) -> None:
    payload = operation.payload
    if operation.kind == "insert_clip":
        _restore_clip_row(db, sequence, payload)
    elif operation.kind == "delete_clip":
        _delete_clip_row(db, payload["clip_id"])
    elif operation.kind == "move_clip":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.timeline_start = payload["timeline_start"]
        clip.track_id = payload["track_id"]
    elif operation.kind == "trim_clip":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.timeline_start = payload["timeline_start"]
        clip.src_in = payload["src_in"]
        clip.src_out = payload["src_out"]
    elif operation.kind == "apply_transcript_edit":
        _delete_clip_row(db, payload["original"]["clip_id"])
        for created in payload["created"]:
            _restore_clip_row(db, sequence, created)
    else:
        raise SequenceDomainError(f"Operation {operation.kind} cannot be redone")


def _require_clip_row(db: Session, clip_id: str) -> Clip:
    clip = db.get(Clip, clip_id)
    if clip is None:
        raise SequenceDomainError("Clip referenced by history no longer exists")
    return clip


def _delete_clip_row(db: Session, clip_id: str) -> None:
    clip = db.get(Clip, clip_id)
    if clip is not None:
        db.delete(clip)


def _restore_clip_row(db: Session, sequence: Sequence, payload: dict) -> None:
    db.add(
        Clip(
            id=payload["clip_id"],
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            track_id=payload["track_id"],
            asset_id=payload["asset_id"],
            timeline_start=payload["timeline_start"],
            src_in=payload["src_in"],
            src_out=payload["src_out"],
        )
    )
