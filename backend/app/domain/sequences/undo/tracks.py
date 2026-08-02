"""轨道级操作的逆向/正向重放:增删、排序、状态,以及分离音频。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Clip, Sequence, Track
from app.domain.sequences.errors import SequenceDomainError
from app.domain.sequences.undo import undoable
from app.domain.sequences.undo.rows import delete_clip_row, require_clip_row, restore_clip_row


@undoable("add_track")
class AddTrack:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        track = db.get(Track, payload["track_id"])
        if track is not None:
            if track.clips:
                raise SequenceDomainError("轨道上还有片段,撤销不了「新建轨道」")
            db.delete(track)

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        db.add(
            Track(
                id=payload["track_id"],
                sequence_id=sequence.id,
                kind=payload["kind"],
                name=payload["name"],
                position=payload["position"],
            )
        )


@undoable("remove_track")
class RemoveTrack:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
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
        db.flush()  # 轨道行要先存在,它的片段才能引用它
        for clip in payload.get("clips", []):
            restore_clip_row(db, sequence, clip)

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        track = db.get(Track, payload["track_id"])
        if track is not None:
            # 重做要把撤销放回去的东西一起删掉,片段也算。在这里拒绝的话,用户撤销了一次
            # 「删除带片段的轨道」之后就卡在两个状态中间了。
            for clip in list(track.clips):
                db.delete(clip)
            db.delete(track)


@undoable("move_track")
class MoveTrack:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        track = db.get(Track, payload["track_id"])
        other = db.get(Track, payload["other_id"])
        if track is not None and other is not None:
            track.position, other.position = payload["track_prev"], payload["other_prev"]

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        track = db.get(Track, payload["track_id"])
        other = db.get(Track, payload["other_id"])
        if track is not None and other is not None:  # 重放那次对调
            track.position, other.position = payload["other_prev"], payload["track_prev"]


@undoable("set_track_state")
class SetTrackState:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        track = db.get(Track, payload["track_id"])
        if track is not None:
            prev = payload["previous"]
            track.muted, track.locked = prev["muted"], prev["locked"]
            track.solo, track.duck = prev.get("solo", False), prev.get("duck", False)

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        track = db.get(Track, payload["track_id"])
        if track is not None:
            track.muted, track.locked = payload["muted"], payload["locked"]
            track.solo, track.duck = payload.get("solo", False), payload.get("duck", False)


@undoable("detach_clip_audio")
class DetachClipAudio:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        delete_clip_row(db, payload["audio_clip"]["id"])
        if payload.get("created_track"):
            created = db.get(Track, payload["created_track"]["id"])
            if created is not None:
                db.delete(created)
        require_clip_row(db, payload["video_clip_id"]).muted = payload["video_muted_prev"]

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        created = payload.get("created_track")
        if created and db.get(Track, created["id"]) is None:
            db.add(Track(id=created["id"], sequence_id=sequence.id, kind="audio",
                         name=created["name"], position=created["position"]))
        audio = payload["audio_clip"]
        db.add(Clip(id=audio["id"], workspace_id=sequence.workspace_id, sequence_id=sequence.id,
                    track_id=audio["track_id"], asset_id=audio["asset_id"],
                    timeline_start=audio["timeline_start"], src_in=audio["src_in"],
                    src_out=audio["src_out"], speed=audio["speed"], gain=audio["gain"]))
        require_clip_row(db, payload["video_clip_id"]).muted = True
