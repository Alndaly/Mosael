from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Clip, Sequence, SequenceOperation, Track
from app.domain.sequences.operations import SequenceDomainError, _record_operation, _require_sequence

"""
Undo/redo over the SequenceOperation log (plan §10.2).

Model: edit operations are appended forever. Undo applies an operation's
inverse, marks it reverted, and appends an "undo" op; redo re-applies the
original, un-reverts it, and appends a "redo" op. A fresh edit after an undo
invalidates the redo stack (checked by revision ordering).
"""

UNDOABLE_KINDS = (
    "insert_clip",
    "move_clip",
    "trim_clip",
    "delete_clip",
    "apply_transcript_edit",
    "add_track",
    "remove_track",
    "move_track",
    "insert_clips_batch",
    "set_clip_effect",
    "split_clip",
    "set_track_state",
    "ripple_delete_clip",
    "set_clip_speed",
    "set_clip_gain",
    "detach_clip_audio",
    "set_clip_transform",
    "set_sequence_reframe",
    "set_clip_text",
    "set_subtitle_style",
)


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
        for entry in payload.get("shifted", []):
            other = _require_clip_row(db, entry["clip_id"])
            other.timeline_start = entry["previous_timeline_start"]
    elif operation.kind == "trim_clip":
        clip = _require_clip_row(db, payload["clip_id"])
        previous = payload["previous"]
        clip.timeline_start = previous["timeline_start"]
        clip.src_in = previous["src_in"]
        clip.src_out = previous["src_out"]
    elif operation.kind in ("apply_transcript_edit", "split_clip"):
        for created in payload["created"]:
            _delete_clip_row(db, created["clip_id"])
        _restore_clip_row(db, sequence, payload["original"])
    elif operation.kind == "insert_clips_batch":
        for created in payload["created"]:
            _delete_clip_row(db, created["clip_id"])
    elif operation.kind == "ripple_delete_clip":
        for entry in payload["shifted"]:
            clip = _require_clip_row(db, entry["clip_id"])
            clip.timeline_start = entry["previous_timeline_start"]
        _restore_clip_row(db, sequence, payload["original"])
    elif operation.kind == "set_track_state":
        track = db.get(Track, payload["track_id"])
        if track is not None:
            prev = payload["previous"]
            track.muted, track.locked = prev["muted"], prev["locked"]
            track.solo, track.duck = prev.get("solo", False), prev.get("duck", False)
    elif operation.kind == "move_track":
        track = db.get(Track, payload["track_id"])
        other = db.get(Track, payload["other_id"])
        if track is not None and other is not None:
            track.position, other.position = payload["track_prev"], payload["other_prev"]
    elif operation.kind == "add_track":
        track = db.get(Track, payload["track_id"])
        if track is not None:
            if track.clips:
                raise SequenceDomainError("Cannot undo add_track while the track has clips")
            db.delete(track)
    elif operation.kind == "remove_track":
        db.add(
            Track(
                id=payload["track_id"],
                sequence_id=sequence.id,
                kind=payload["kind"],
                name=payload["name"],
                position=payload["position"],
            )
        )
    elif operation.kind == "set_clip_effect":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.effects = payload["previous"]
    elif operation.kind == "set_clip_speed":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.speed = payload["previous"]
    elif operation.kind == "set_clip_gain":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.gain = payload["previous"]["gain"]
        clip.muted = payload["previous"]["muted"]
    elif operation.kind == "detach_clip_audio":
        _delete_clip_row(db, payload["audio_clip"]["id"])
        if payload.get("created_track"):
            created = db.get(Track, payload["created_track"]["id"])
            if created is not None:
                db.delete(created)
        video = _require_clip_row(db, payload["video_clip_id"])
        video.muted = payload["video_muted_prev"]
    elif operation.kind == "set_clip_transform":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.transform = payload["previous"]
    elif operation.kind == "set_sequence_reframe":
        prev = payload["previous"]
        sequence.width, sequence.height, sequence.reframe = prev["width"], prev["height"], prev["reframe"]
    elif operation.kind == "set_subtitle_style":
        sequence.subtitle_style = payload["previous"]
    elif operation.kind == "set_clip_text":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.text_override = payload["previous"]
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
        for entry in payload.get("shifted", []):
            other = _require_clip_row(db, entry["clip_id"])
            other.timeline_start = entry["timeline_start"]
    elif operation.kind == "trim_clip":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.timeline_start = payload["timeline_start"]
        clip.src_in = payload["src_in"]
        clip.src_out = payload["src_out"]
    elif operation.kind in ("apply_transcript_edit", "split_clip"):
        _delete_clip_row(db, payload["original"]["clip_id"])
        for created in payload["created"]:
            _restore_clip_row(db, sequence, created)
    elif operation.kind == "insert_clips_batch":
        for created in payload["created"]:
            _restore_clip_row(db, sequence, created)
    elif operation.kind == "ripple_delete_clip":
        _delete_clip_row(db, payload["original"]["clip_id"])
        for entry in payload["shifted"]:
            clip = _require_clip_row(db, entry["clip_id"])
            clip.timeline_start = entry["timeline_start"]
    elif operation.kind == "set_track_state":
        track = db.get(Track, payload["track_id"])
        if track is not None:
            track.muted, track.locked = payload["muted"], payload["locked"]
            track.solo, track.duck = payload.get("solo", False), payload.get("duck", False)
    elif operation.kind == "move_track":
        track = db.get(Track, payload["track_id"])
        other = db.get(Track, payload["other_id"])
        if track is not None and other is not None:  # redo the swap
            track.position, other.position = payload["other_prev"], payload["track_prev"]
    elif operation.kind == "add_track":
        db.add(
            Track(
                id=payload["track_id"],
                sequence_id=sequence.id,
                kind=payload["kind"],
                name=payload["name"],
                position=payload["position"],
            )
        )
    elif operation.kind == "remove_track":
        track = db.get(Track, payload["track_id"])
        if track is not None:
            if track.clips:
                raise SequenceDomainError("Cannot redo remove_track while the track has clips")
            db.delete(track)
    elif operation.kind == "set_clip_effect":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.effects = payload["effects"]
    elif operation.kind == "set_clip_speed":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.speed = payload["speed"]
    elif operation.kind == "set_clip_gain":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.gain = payload["gain"]
        clip.muted = payload["muted"]
    elif operation.kind == "detach_clip_audio":
        created = payload.get("created_track")
        if created and db.get(Track, created["id"]) is None:
            db.add(Track(id=created["id"], sequence_id=sequence.id, kind="audio",
                         name=created["name"], position=created["position"]))
        ac = payload["audio_clip"]
        db.add(Clip(id=ac["id"], workspace_id=sequence.workspace_id, sequence_id=sequence.id,
                    track_id=ac["track_id"], asset_id=ac["asset_id"], timeline_start=ac["timeline_start"],
                    src_in=ac["src_in"], src_out=ac["src_out"], speed=ac["speed"], gain=ac["gain"]))
        video = _require_clip_row(db, payload["video_clip_id"])
        video.muted = True
    elif operation.kind == "set_clip_transform":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.transform = payload["transform"]
    elif operation.kind == "set_sequence_reframe":
        sequence.width, sequence.height, sequence.reframe = payload["width"], payload["height"], payload["reframe"]
    elif operation.kind == "set_subtitle_style":
        sequence.subtitle_style = payload["style"]
    elif operation.kind == "set_clip_text":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.text_override = payload["text"]
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
            asset_id=payload.get("asset_id"),
            timeline_start=payload["timeline_start"],
            src_in=payload["src_in"],
            src_out=payload["src_out"],
            text_override=payload.get("text_override"),
        )
    )
