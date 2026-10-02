"""改动日志(sequences/journal.py)的倒放与重放:撤销倒着还原每一条,重做顺着再做一遍。"""

from __future__ import annotations

import copy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Clip, Sequence, Track
from app.domain.sequences.errors import SequenceDomainError
from app.domain.sequences.undo.rows import delete_clip_row, require_clip_row, restore_clip_row


def replay_backward(db: Session, sequence: Sequence, entries: list[dict[str, Any]]) -> None:
    """撤销:倒着把每一条还原回去。"""
    for entry in reversed(entries):
        op = entry["op"]
        if op == "create":
            delete_clip_row(db, entry["clip"]["clip_id"])
        elif op == "delete":
            restore_clip_row(db, sequence, entry["clip"])
        elif op == "update":
            clip = require_clip_row(db, entry["clip_id"])
            for name, value in entry["before"].items():
                setattr(clip, name, copy.deepcopy(value))
        elif op == "create_track":
            _drop_track(db, entry["track"]["id"])
        else:
            raise SequenceDomainError("seqErr_notUndoable", kind=op)
        db.flush()


def replay_forward(db: Session, sequence: Sequence, entries: list[dict[str, Any]]) -> None:
    """重做:顺着把每一条再做一遍。按原 id 重建,后面的条目才认得出它们。"""
    for entry in entries:
        op = entry["op"]
        if op == "create":
            restore_clip_row(db, sequence, entry["clip"])
        elif op == "delete":
            delete_clip_row(db, entry["clip"]["clip_id"])
        elif op == "update":
            clip = require_clip_row(db, entry["clip_id"])
            for name, value in entry["after"].items():
                setattr(clip, name, copy.deepcopy(value))
        elif op == "create_track":
            track = entry["track"]
            if db.get(Track, track["id"]) is None:
                db.add(
                    Track(
                        id=track["id"],
                        sequence_id=sequence.id,
                        kind=track["kind"],
                        name=track["name"],
                        position=track["position"],
                        role=track["role"],
                    )
                )
        else:
            raise SequenceDomainError("seqErr_notUndoable", kind=op)
        db.flush()


def _drop_track(db: Session, track_id: str) -> None:
    track = db.get(Track, track_id)
    if track is None:
        return
    # 撤销是线性的:轨上后来放的东西应当已经先被撤掉了。还剩片段说明有人绕过了撤销栈,删轨会连它们一起删。
    if db.scalar(select(Clip.id).where(Clip.track_id == track_id).limit(1)) is not None:
        raise SequenceDomainError("seqErr_undoTrackHasClips")
    db.delete(track)
