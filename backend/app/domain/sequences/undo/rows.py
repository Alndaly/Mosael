"""重放一条操作时反复要做的几件事:找到一行、删掉一行、按记录重建一行。

单独放一个模块,是因为 clips/tracks/properties 三边都要用,而它们互不认识。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import Asset, Clip, Sequence
from app.domain.sequences.errors import SequenceDomainError


def require_clip_row(db: Session, clip_id: str) -> Clip:
    clip = db.get(Clip, clip_id)
    if clip is None:
        # 这句话会原样出现在用户的提示条里(EditorView 的 undo/redo 接了 onError),所以说人话。
        raise SequenceDomainError("seqErr_undoClipGone")
    return clip


def delete_clip_row(db: Session, clip_id: str) -> None:
    clip = db.get(Clip, clip_id)
    if clip is not None:
        db.delete(clip)


def restore_clip_row(db: Session, sequence: Sequence, payload: dict) -> None:
    """按记录重建一个片段 —— 位置之外的一切也照原样(RESTORABLE_CLIP_FIELDS)。

    只还原位置的话,每一次"让片段复活"的撤销 —— 删除、涟漪删除、字幕编辑、切分 —— 都会悄悄
    把它交还成 1 倍速、单位增益、没有静音、没有调色,字幕还是空的。

    **素材可能在这条记录之后被删掉了。** 那时按旧 asset_id 重建,外键(RESTRICT)当场
    IntegrityError —— 而撤销栈是按顺序往回走的,这一条撤不掉,它前面的所有历史也跟着永远
    撤不到了。删素材时,时间线上还在的片段会转成脱机占位;撤销还回来的片段也该是同一个样子,
    用的是记录这一步时留下的那份素材快照(_clip_payload 的 asset_snapshot)。
    """
    asset_id = payload["asset_id"]
    offline_asset = payload["offline_asset"]
    if asset_id is not None and db.get(Asset, asset_id) is None:
        asset_id, offline_asset = None, payload["asset_snapshot"]
    db.add(
        Clip(
            id=payload["clip_id"],
            workspace_id=sequence.workspace_id,
            sequence_id=sequence.id,
            track_id=payload["track_id"],
            asset_id=asset_id,
            offline_asset=offline_asset,
            timeline_start=payload["timeline_start"],
            src_in=payload["src_in"],
            src_out=payload["src_out"],
            speed=payload["speed"],
            gain=payload["gain"],
            muted=payload["muted"],
            effects=payload["effects"] or {},
            transform=payload["transform"] or {},
            text_override=payload["text_override"],
            link_group=payload["link_group"],
        )
    )
