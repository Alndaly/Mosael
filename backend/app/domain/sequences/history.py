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
    "move_clips_batch",
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
    "set_clip_texts_batch",
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


def _undo_ripple_room(db: Session, payload: dict) -> None:
    """撤销插入编辑的"让位":右移的片段归位;落点处若切开过跨越片段,
    删掉切出的尾段、把原片段的 src_out 补回去。"""
    for entry in payload.get("shifted", []):
        other = _require_clip_row(db, entry["clip_id"])
        other.timeline_start = entry["previous_timeline_start"]
    split = payload.get("split")
    if split:
        _delete_clip_row(db, split["tail"]["clip_id"])
        _require_clip_row(db, split["clip_id"]).src_out = split["previous_src_out"]


def _redo_ripple_room(db: Session, sequence: Sequence, payload: dict) -> None:
    """重做让位:先复原切割(收短原片段 + 原 id 重建尾段),再重放右移。"""
    split = payload.get("split")
    if split:
        _require_clip_row(db, split["clip_id"]).src_out = split["tail"]["src_in"]
        _restore_clip_row(db, sequence, split["tail"])
        db.flush()  # 尾段也在 shifted 里,下面的 db.get 要能查到它
    for entry in payload.get("shifted", []):
        other = _require_clip_row(db, entry["clip_id"])
        other.timeline_start = entry["timeline_start"]


def _apply_inverse(db: Session, sequence: Sequence, operation: SequenceOperation) -> None:
    payload = operation.payload
    if operation.kind == "insert_clip":
        _delete_clip_row(db, payload["clip_id"])
        _undo_ripple_room(db, payload)
    elif operation.kind == "delete_clip":
        _restore_clip_row(db, sequence, payload)
    elif operation.kind == "move_clip":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.timeline_start = payload["previous_timeline_start"]
        clip.track_id = payload.get("previous_track_id", clip.track_id)
        _undo_ripple_room(db, payload)
    elif operation.kind == "move_clips_batch":
        # 整组一步退回:组拖记的是一条操作,撤销就该把整组还原,而不是退回其中一个。
        for entry in payload["moved"]:
            clip = _require_clip_row(db, entry["clip_id"])
            clip.timeline_start = entry["previous_timeline_start"]
            clip.track_id = entry["previous_track_id"]
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
                muted=payload.get("muted", False),
                solo=payload.get("solo", False),
                locked=payload.get("locked", False),
                duck=payload.get("duck", False),
            )
        )
        db.flush()  # the track row must exist before its clips reference it
        for clip in payload.get("clips", []):
            _restore_clip_row(db, sequence, clip)
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
    elif operation.kind == "set_clip_texts_batch":
        for entry in payload["entries"]:
            _require_clip_row(db, entry["clip_id"]).text_override = entry["previous"]
    else:
        raise SequenceDomainError(f"Operation {operation.kind} cannot be undone")


def _apply_forward(db: Session, sequence: Sequence, operation: SequenceOperation) -> None:
    payload = operation.payload
    if operation.kind == "insert_clip":
        _restore_clip_row(db, sequence, payload)
        _redo_ripple_room(db, sequence, payload)
    elif operation.kind == "delete_clip":
        _delete_clip_row(db, payload["clip_id"])
    elif operation.kind == "move_clip":
        clip = _require_clip_row(db, payload["clip_id"])
        clip.timeline_start = payload["timeline_start"]
        clip.track_id = payload["track_id"]
        _redo_ripple_room(db, sequence, payload)
    elif operation.kind == "move_clips_batch":
        for entry in payload["moved"]:
            clip = _require_clip_row(db, entry["clip_id"])
            clip.timeline_start = entry["timeline_start"]
            clip.track_id = entry["track_id"]
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
            # Redo removes whatever the undo put back, clips included — refusing here would
            # strand the user between two states after undoing a with-clips removal.
            for clip in list(track.clips):
                db.delete(clip)
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
    elif operation.kind == "set_clip_texts_batch":
        for entry in payload["entries"]:
            _require_clip_row(db, entry["clip_id"]).text_override = entry["text"]
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
    """Rebuild a clip from a recorded payload.

    Restoring only position used to mean every undo that resurrects a clip — delete, ripple
    delete, transcript edit, split — silently handed back a clip at 1x, unity gain, unmuted,
    ungraded and, for a subtitle, blank. Defaults are applied per field so payloads recorded
    before RESTORABLE_CLIP_FIELDS existed still replay instead of raising.
    """
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
            speed=payload.get("speed", 1.0),
            gain=payload.get("gain", 1.0),
            muted=payload.get("muted", False),
            linked_clip_id=payload.get("linked_clip_id"),
            effects=payload.get("effects") or {},
            transform=payload.get("transform") or {},
            text_override=payload.get("text_override"),
        )
    )
