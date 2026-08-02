"""重放一条操作时反复要做的几件事:找到一行、删掉一行、按记录重建一行。

单独放一个模块,是因为 clips/tracks/properties 三边都要用,而它们互不认识。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Clip, Sequence
from app.domain.sequences.errors import SequenceDomainError


def require_clip_row(db: Session, clip_id: str) -> Clip:
    clip = db.get(Clip, clip_id)
    if clip is None:
        # 这句话会原样出现在用户的提示条里(EditorView 的 undo/redo 接了 onError),所以说人话。
        raise SequenceDomainError("这一步引用的片段已经不在了,撤销不了")
    return clip


def delete_clip_row(db: Session, clip_id: str) -> None:
    clip = db.get(Clip, clip_id)
    if clip is not None:
        db.delete(clip)


def restore_clip_row(db: Session, sequence: Sequence, payload: dict) -> None:
    """按记录重建一个片段。

    只还原位置的话,每一次"让片段复活"的撤销 —— 删除、涟漪删除、字幕编辑、切分 —— 都会悄悄
    把它交还成 1 倍速、单位增益、没有静音、没有调色,字幕还是空的。逐字段给默认值,是为了让
    RESTORABLE_CLIP_FIELDS 出现之前记下的旧 payload 仍然能重放,而不是抛错。
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


def undo_ripple_room(db: Session, payload: dict) -> None:
    """撤销插入编辑的「让位」:右移的片段归位;落点处若切开过跨越片段,
    删掉切出的尾段、把原片段的 src_out 补回去。"""
    for entry in payload.get("shifted", []):
        other = require_clip_row(db, entry["clip_id"])
        other.timeline_start = entry["previous_timeline_start"]
    split = payload.get("split")
    if split:
        delete_clip_row(db, split["tail"]["clip_id"])
        require_clip_row(db, split["clip_id"]).src_out = split["previous_src_out"]


def redo_ripple_room(db: Session, sequence: Sequence, payload: dict) -> None:
    """重做让位:先复原切割(收短原片段 + 原 id 重建尾段),再重放右移。"""
    split = payload.get("split")
    if split:
        require_clip_row(db, split["clip_id"]).src_out = split["tail"]["src_in"]
        restore_clip_row(db, sequence, split["tail"])
        db.flush()  # 尾段也在 shifted 里,下面的 db.get 要能查到它
    for entry in payload.get("shifted", []):
        other = require_clip_row(db, entry["clip_id"])
        other.timeline_start = entry["timeline_start"]
