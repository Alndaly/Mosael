"""时间线的撤销/重做栈(plan §10.2)。

模型:编辑操作只追加不删除。撤销 = 应用某条操作的逆操作、把它标记成已撤销、再追加一条
"undo" 记账;重做 = 重新应用原操作、清掉它的已撤销标记、追加一条 "redo"。撤销之后再做一次
新编辑,重做栈失效(靠 revision 顺序判断)。

**怎么撤销**不在这个文件里 —— 那是 undo/ 注册表的事(每种操作成对登记逆向与正向)。这里只
管队列本身:往回找到该撤销的那一条,以及决定还能不能撤销/重做。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Sequence, SequenceOperation
from app.domain.sequences import undo as undo_registry
from app.domain.sequences.errors import SequenceDomainError
from app.domain.sequences.operations import _record_operation, _require_sequence

#: 可撤销的操作类型 —— **派生**自注册表,不是另一份手写清单。
#:
#: 曾经这是一个手写元组,和 operations.py 里的 24 处 _record_operation 各自维护。两边不同步
#: 时的表现极坏:往回找的时候按 kind 过滤,于是它跳过刚做的那条,把**更早的一条编辑**撤了 ——
#: 200,没有报错,can_undo 一直是 true。用户按一次 ⌘Z,消失的是他没打算撤销的东西。
UNDOABLE_KINDS = undo_registry.undoable_kinds()


def undo(db: Session, sequence_id: str) -> Sequence:
    sequence = _require_sequence(db, sequence_id)
    operation = _latest_undoable(db, sequence_id)
    if operation is None:
        raise SequenceDomainError("没有可撤销的操作")
    # kind 不在注册表里就直接报错。往回跳过这一条去撤更早的,等于替用户丢掉一件他没要求撤销的事。
    undo_registry.apply_inverse(db, sequence, operation.kind, operation.payload)
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
        raise SequenceDomainError("没有可重做的操作")
    original = db.get(SequenceOperation, undo_operation.undo_of or "")
    if original is None:
        raise SequenceDomainError("没有可重做的操作")
    undo_registry.apply_forward(db, sequence, original.kind, original.payload)
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
    """往回找到该撤销的那一条 —— 最新的、还没被撤销过的、不是记账的那一条。

    过滤条件刻意**不是**「kind 在可撤销清单里」。那样写的话,一条没登记逆操作的编辑会被
    静默跳过,撤销落到更早的一条上;现在它会被选中,然后在注册表里明确报错。宁可告诉用户
    「这个操作撤不了」,也不能替他撤掉别的东西。
    """
    return db.scalar(
        select(SequenceOperation)
        .where(
            SequenceOperation.sequence_id == sequence_id,
            SequenceOperation.kind.notin_(tuple(undo_registry.NOT_UNDOABLE)),
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
            SequenceOperation.kind.notin_(tuple(undo_registry.NOT_UNDOABLE)),
            SequenceOperation.revision_after > revision,
        )
        .limit(1)
    )
    return newer is not None
