"""片段级操作的逆向/正向重放:插入、删除、移动、裁剪、切分。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Sequence
from app.domain.sequences.undo import undoable
from app.domain.sequences.undo.rows import (
    delete_clip_row,
    redo_ripple_room,
    require_clip_row,
    restore_clip_row,
    undo_ripple_room,
)


@undoable("insert_clip")
class InsertClip:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        delete_clip_row(db, payload["clip_id"])
        undo_ripple_room(db, payload)

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        restore_clip_row(db, sequence, payload)
        redo_ripple_room(db, sequence, payload)


@undoable("insert_clips_batch")
class InsertClipsBatch:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        for created in payload["created"]:
            delete_clip_row(db, created["clip_id"])

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        for created in payload["created"]:
            restore_clip_row(db, sequence, created)


@undoable("delete_clip")
class DeleteClip:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        restore_clip_row(db, sequence, payload)

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        delete_clip_row(db, payload["clip_id"])


@undoable("delete_clips_batch")
class DeleteClipsBatch:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        for entry in payload["deleted"]:
            restore_clip_row(db, sequence, entry)

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        for entry in payload["deleted"]:
            delete_clip_row(db, entry["clip_id"])


@undoable("ripple_delete_clip")
class RippleDeleteClip:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        for entry in payload["shifted"]:
            require_clip_row(db, entry["clip_id"]).timeline_start = entry["previous_timeline_start"]
        restore_clip_row(db, sequence, payload["original"])

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        delete_clip_row(db, payload["original"]["clip_id"])
        for entry in payload["shifted"]:
            require_clip_row(db, entry["clip_id"]).timeline_start = entry["timeline_start"]


@undoable("ripple_delete_clips_batch")
class RippleDeleteClipsBatch:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        # 逆序回放:删除时是从后往前删的,撤销要从前往后还原,位移才能层层退回。
        for entry in reversed(payload["entries"]):
            for shifted in entry["shifted"]:
                require_clip_row(db, shifted["clip_id"]).timeline_start = shifted["previous_timeline_start"]
            restore_clip_row(db, sequence, entry["original"])

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        for entry in payload["entries"]:
            delete_clip_row(db, entry["original"]["clip_id"])
            for shifted in entry["shifted"]:
                require_clip_row(db, shifted["clip_id"]).timeline_start = shifted["timeline_start"]


@undoable("move_clip")
class MoveClip:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        clip = require_clip_row(db, payload["clip_id"])
        clip.timeline_start = payload["previous_timeline_start"]
        clip.track_id = payload.get("previous_track_id", clip.track_id)
        undo_ripple_room(db, payload)

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        clip = require_clip_row(db, payload["clip_id"])
        clip.timeline_start = payload["timeline_start"]
        clip.track_id = payload["track_id"]
        redo_ripple_room(db, sequence, payload)


@undoable("move_clips_batch")
class MoveClipsBatch:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        # 整组一步退回:组拖记的是一条操作,撤销就该把整组还原,而不是退回其中一个。
        for entry in payload["moved"]:
            clip = require_clip_row(db, entry["clip_id"])
            clip.timeline_start = entry["previous_timeline_start"]
            clip.track_id = entry["previous_track_id"]

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        for entry in payload["moved"]:
            clip = require_clip_row(db, entry["clip_id"])
            clip.timeline_start = entry["timeline_start"]
            clip.track_id = entry["track_id"]


@undoable("trim_clip")
class TrimClip:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        clip = require_clip_row(db, payload["clip_id"])
        previous = payload["previous"]
        clip.timeline_start = previous["timeline_start"]
        clip.src_in = previous["src_in"]
        clip.src_out = previous["src_out"]

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        clip = require_clip_row(db, payload["clip_id"])
        clip.timeline_start = payload["timeline_start"]
        clip.src_in = payload["src_in"]
        clip.src_out = payload["src_out"]


@undoable("split_clip")
class SplitClip:
    """一个原片段换成若干新片段。"""

    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        for created in payload["created"]:
            delete_clip_row(db, created["clip_id"])
        restore_clip_row(db, sequence, payload["original"])

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        delete_clip_row(db, payload["original"]["clip_id"])
        for created in payload["created"]:
            restore_clip_row(db, sequence, created)


# 字幕编辑落到时间线上就是「一个片段换成若干片段」,和切分同一个形状,复用同一对实现。
undoable("apply_transcript_edit")(SplitClip)


@undoable("apply_transcript_edits_batch")
class TranscriptEditsBatch:
    """Several original clips replaced together by one transcript gesture."""

    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        for edit in reversed(payload["edits"]):
            SplitClip.inverse(db, sequence, edit)

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        for edit in payload["edits"]:
            SplitClip.forward(db, sequence, edit)
