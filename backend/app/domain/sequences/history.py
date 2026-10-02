"""时间线的撤销/重做栈(plan §10.2)。

模型:编辑操作只追加不删除。撤销 = 应用某条操作的逆操作、把它标记成已撤销、再追加一条
"undo" 记账;重做 = 重新应用原操作、清掉它的已撤销标记、追加一条 "redo"。撤销之后再做一次
新编辑,重做栈失效(靠 revision 顺序判断)。

**怎么撤销**不在这个文件里 —— 那是 undo/ 注册表的事(每种操作成对登记逆向与正向)。这里只
管队列本身:往回找到该撤销的那一条,以及决定还能不能撤销/重做。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Sequence, SequenceOperation
from app.domain.sequences import concurrency
from app.domain.sequences import undo as undo_registry
from app.domain.sequences._timeline import _record_operation, _require_sequence
from app.domain.sequences.errors import SequenceDomainError

#: 可撤销的操作类型 —— **派生**自注册表,不是另一份手写清单。
#:
#: 曾经这是一个手写元组,和 operations.py 里的 24 处 _record_operation 各自维护。两边不同步
#: 时的表现极坏:往回找的时候按 kind 过滤,于是它跳过刚做的那条,把**更早的一条编辑**撤了 ——
#: 200,没有报错,can_undo 一直是 true。用户按一次 ⌘Z,消失的是他没打算撤销的东西。
UNDOABLE_KINDS = undo_registry.undoable_kinds()


def _expect(db: Session, sequence: Sequence, expected_revision: int | None, actor_id: str | None) -> None:
    """调用方说了「我看到的是第几版」(画板上的撤销:它只知道自己做的那一步):不是这一版就拒,不去撤别人的那一步,
    并说清是谁改的。"""
    if expected_revision is not None and sequence.revision != expected_revision:
        later = concurrency.effective_after(db, sequence.id, min(expected_revision, sequence.revision))
        raise concurrency.conflict(db, sequence, expected_revision, later, actor_id=actor_id)


def _ensure_reversible(
    db: Session, sequence: Sequence, target: SequenceOperation, expected_revision: int | None, actor_id: str | None
) -> None:
    """「只撤我自己的」:要撤 / 重做的那一步不一定是最新的一步 —— 它之后别人可能又做了几步。那几步每一步都得和它
    能交换(见 concurrency):别人把这个片段挪了、切了,再按老记录把它挪回去,就把别人的改动一起打乱了。

    这时调用方手里的版本号落后也没关系:要不要撤,看的是这一步之后发生了什么,不是调用方看没看到。
    只有版本号比现在还新(对不上)才拒。
    """
    if expected_revision is not None and expected_revision > sequence.revision:
        raise concurrency.conflict(db, sequence, expected_revision, [], actor_id=actor_id)
    later = concurrency.effective_after(db, sequence.id, target.revision_after)
    blocking = concurrency.clashing(db, concurrency.footprint_of_operation(db, target), later)
    if blocking:
        raise concurrency.conflict(db, sequence, expected_revision, blocking, actor_id=actor_id, key="seqErr_undoBlockedBy")


def undo(
    db: Session,
    sequence_id: str,
    *,
    expected_revision: int | None = None,
    actor_id: str | None = None,
    mine: bool = False,
) -> Sequence:
    """撤一步。缺省撤**整条时间线上最新的一步**;`mine` 撤**这个人自己最近的一步**(剪辑页的 ⌘Z:几个人一起剪时,
    按一下撤掉的不该是同事刚做的那一下)。"""
    sequence = _require_sequence(db, sequence_id)
    if mine:
        operation = _latest_undoable(db, sequence_id, actor_id=actor_id, mine=True)
        if operation is None:
            raise SequenceDomainError("seqErr_nothingOfYoursToUndo")
        _ensure_reversible(db, sequence, operation, expected_revision, actor_id)
    else:
        _expect(db, sequence, expected_revision, actor_id)
        operation = _latest_undoable(db, sequence_id)
        if operation is None:
            raise SequenceDomainError("seqErr_nothingToUndo")
    # kind 不在注册表里就直接报错。往回跳过这一条去撤更早的,等于替用户丢掉一件他没要求撤销的事。
    _replay(db, lambda: undo_registry.apply_inverse(db, sequence, operation.kind, operation.payload))
    operation.reverted = True
    _record_operation(
        db,
        sequence,
        kind="undo",
        payload={"undo_of": operation.id, "undone_kind": operation.kind},
        summary={"operation": "undo", "undone_kind": operation.kind},
        actor_id=actor_id,
        undo_of=operation.id,
    )
    return sequence


def redo(
    db: Session,
    sequence_id: str,
    *,
    expected_revision: int | None = None,
    actor_id: str | None = None,
    mine: bool = False,
) -> Sequence:
    """重做一步。`mine` 同撤销:重做这个人自己撤掉的那一步;他撤销之后自己又做了新的编辑,就没有可重做的了。"""
    sequence = _require_sequence(db, sequence_id)
    if mine:
        undo_operation = _latest_active_undo(db, sequence_id, actor_id=actor_id, mine=True)
        if undo_operation is None or _has_edit_after(db, sequence_id, undo_operation.revision_after, actor_id=actor_id, mine=True):
            raise SequenceDomainError("seqErr_nothingToRedo")
    else:
        _expect(db, sequence, expected_revision, actor_id)
        undo_operation = _latest_active_undo(db, sequence_id)
        if undo_operation is None or _has_edit_after(db, sequence_id, undo_operation.revision_after):
            raise SequenceDomainError("seqErr_nothingToRedo")
    original = db.get(SequenceOperation, undo_operation.undo_of or "")
    if original is None:
        raise SequenceDomainError("seqErr_nothingToRedo")
    if mine:
        _ensure_reversible(db, sequence, undo_operation, expected_revision, actor_id)
    _replay(db, lambda: undo_registry.apply_forward(db, sequence, original.kind, original.payload))
    original.reverted = False
    undo_operation.reverted = True
    _record_operation(
        db,
        sequence,
        kind="redo",
        payload={"redo_of": original.id, "redone_kind": original.kind},
        summary={"operation": "redo", "redone_kind": original.kind},
        actor_id=actor_id,
        undo_of=undo_operation.id,
    )
    return sequence


def _replay(db: Session, apply: Callable[[], None]) -> None:
    """重放一条记录,数据库不收就说人话。

    重放是照着当时的记录重建行,而记录之后世界变了:素材被删了、轨道被别处删了。重放各自尽量绕开
    这些(见 undo/rows.restore_clip_row 的脱机重建),绕不开的落到这里 —— 此前它是一个 IntegrityError
    一路冒成 500,前端只看到「出错了」,撤销按钮还亮着,再按一次还是 500。
    """
    try:
        apply()
        db.flush()
    except IntegrityError as exc:
        raise SequenceDomainError("seqErr_replayConflict") from exc


@dataclass(frozen=True)
class HistoryStep:
    """撤销 / 重做作为一条编辑操作(智能体、工作流的 `{"kind": "undo"}`)。撤的是整条时间线上最新的一步;
    `expected_revision` 给了而时间线已经改过,就不撤(见 undo)。"""

    expected_revision: int | None = None
    actor_id: str | None = None


def undo_step(db: Session, sequence_id: str, op: HistoryStep) -> Sequence:
    return undo(db, sequence_id, expected_revision=op.expected_revision, actor_id=op.actor_id)


def redo_step(db: Session, sequence_id: str, op: HistoryStep) -> Sequence:
    return redo(db, sequence_id, expected_revision=op.expected_revision, actor_id=op.actor_id)


def can_undo(db: Session, sequence_id: str) -> bool:
    return _latest_undoable(db, sequence_id) is not None


def can_redo(db: Session, sequence_id: str) -> bool:
    undo_operation = _latest_active_undo(db, sequence_id)
    return undo_operation is not None and not _has_edit_after(db, sequence_id, undo_operation.revision_after)


def _latest_undoable(
    db: Session, sequence_id: str, *, actor_id: str | None = None, mine: bool = False
) -> SequenceOperation | None:
    """往回找到该撤销的那一条 —— 最新的、还没被撤销过的、不是记账的那一条(`mine`:还得是这个人做的)。

    过滤条件刻意**不是**「kind 在可撤销清单里」。那样写的话,一条没登记逆操作的编辑会被
    静默跳过,撤销落到更早的一条上;现在它会被选中,然后在注册表里明确报错。宁可告诉用户
    「这个操作撤不了」,也不能替他撤掉别的东西。
    """
    query = select(SequenceOperation).where(
        SequenceOperation.sequence_id == sequence_id,
        SequenceOperation.kind.notin_(tuple(undo_registry.NOT_UNDOABLE)),
        SequenceOperation.reverted.is_(False),
    )
    if mine:
        query = query.where(SequenceOperation.actor_id == actor_id)
    return db.scalar(query.order_by(SequenceOperation.revision_after.desc()).limit(1))


def _latest_active_undo(
    db: Session, sequence_id: str, *, actor_id: str | None = None, mine: bool = False
) -> SequenceOperation | None:
    query = select(SequenceOperation).where(
        SequenceOperation.sequence_id == sequence_id,
        SequenceOperation.kind == "undo",
        SequenceOperation.reverted.is_(False),
    )
    if mine:
        query = query.where(SequenceOperation.actor_id == actor_id)
    return db.scalar(query.order_by(SequenceOperation.revision_after.desc()).limit(1))


def _has_edit_after(
    db: Session, sequence_id: str, revision: int, *, actor_id: str | None = None, mine: bool = False
) -> bool:
    query = select(SequenceOperation.id).where(
        SequenceOperation.sequence_id == sequence_id,
        SequenceOperation.kind.notin_(tuple(undo_registry.NOT_UNDOABLE)),
        SequenceOperation.revision_after > revision,
    )
    if mine:
        query = query.where(SequenceOperation.actor_id == actor_id)
    return db.scalar(query.limit(1)) is not None
