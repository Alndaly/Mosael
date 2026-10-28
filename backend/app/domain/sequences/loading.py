"""从库里取一条时间线:只要那一行,或者连轨道和片段整张取出来,并标上「能不能撤销 / 重做」。

调用方已经过了闸(permissions.require_sequence_access)。取不到抛 SequenceNotFound —— 此前每个路由各写一遍
`db.get(Sequence, …)` 再 404 一句写死的英文,而整张取出来那一套(预加载轨道和片段、补撤销标记)也只在路由里。
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Sequence, Track
from app.domain.sequences.errors import SequenceNotFound
from app.domain.sequences.history import can_redo, can_undo


def sequence_row(db: Session, sequence_id: str) -> Sequence:
    """这条时间线那一行(不预加载轨道)。"""
    sequence = db.get(Sequence, sequence_id)
    if sequence is None:
        raise SequenceNotFound("seqErr_sequenceNotFound")
    return sequence


def with_timelines(db: Session, sequence_ids: Iterable[str]) -> list[Sequence]:
    """几条时间线连轨道和片段一起取,各自标上能不能撤销 / 重做(非映射属性,序列化用)。不在的跳过。"""
    ids = list(sequence_ids)
    if not ids:
        return []
    rows = list(db.scalars(
        select(Sequence).where(Sequence.id.in_(ids)).options(selectinload(Sequence.tracks).selectinload(Track.clips))
    ))
    for sequence in rows:
        sequence.can_undo = can_undo(db, sequence.id)
        sequence.can_redo = can_redo(db, sequence.id)
    return rows


def with_timeline(db: Session, sequence_id: str) -> Sequence:
    """一条时间线连轨道和片段一起取(见 with_timelines)。"""
    rows = with_timelines(db, [sequence_id])
    if not rows:
        raise SequenceNotFound("seqErr_sequenceNotFound")
    return rows[0]


__all__ = ["sequence_row", "with_timeline", "with_timelines"]
