"""片段级操作的逆向/正向重放:插入、删除、移动、修剪、切分、按文字剪、变速、分离音频。

这一组操作的 payload 都带一份改动日志(`changes`,见 sequences/journal.py),撤销 / 重做就是把它倒放 /
顺放 —— 一对实现,登记给每一种 kind。覆盖切掉的那一截、链接片段跟着挪的那一下、波纹推开的后续片段,
都在日志里,不会有哪一种操作的还原漏掉它们。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Sequence
from app.domain.sequences.undo.journal import replay_backward, replay_forward
from app.domain.sequences.undo.properties import SetSequenceReframe
from app.domain.sequences.undo.registry import undoable

#: 记改动日志的 kind。和 _record_operation 那一侧的 kind 字面量对得上由 tests/test_undo_registry.py 守着。
JOURNALED_KINDS = (
    "insert_clip",
    "insert_clips_batch",
    "delete_clip",
    "delete_clips_batch",
    "ripple_delete_clip",
    "ripple_delete_clips_batch",
    "move_clip",
    "move_clips_batch",
    "trim_clip",
    "split_clip",
    "apply_transcript_edit",
    "apply_transcript_edits_batch",
    "set_clip_speed",
    "detach_clip_audio",
    "replace_clip_media",
)


class Journaled:
    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        replay_backward(db, sequence, payload["changes"])

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        replay_forward(db, sequence, payload["changes"])


for _kind in JOURNALED_KINDS:
    undoable(_kind)(Journaled)


@undoable("append_asset")
class AppendAsset:
    """接到时间线:空时间线上连带改了画幅。一个手势一步撤销 —— 片段和画幅一起退、一起回。"""

    def inverse(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        replay_backward(db, sequence, payload["changes"])
        if payload["reframe"] is not None:
            SetSequenceReframe.inverse(db, sequence, payload["reframe"])

    def forward(db: Session, sequence: Sequence, payload: dict[str, Any]) -> None:
        if payload["reframe"] is not None:
            SetSequenceReframe.forward(db, sequence, payload["reframe"])
        replay_forward(db, sequence, payload["changes"])
