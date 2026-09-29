"""撤销 / 重做注册表的本体。各操作模块从这里 import `undoable`,包的 `__init__` 负责把它们全部挂上 ——
理由同 workflows/executors/registry.py。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from app.db.models import Sequence
from app.domain.sequences.errors import SequenceDomainError

Applier = Callable[[Session, Sequence, dict[str, Any]], None]


@dataclass(frozen=True)
class UndoPair:
    inverse: Applier
    forward: Applier


_REGISTRY: dict[str, UndoPair] = {}

#: 记录进操作日志、但**故意**不可撤销的 kind → 原因。
#:
#: 只有两条,而且都是撤销机制自己的记账:撤销一条编辑时会追加一条 "undo",重做时追加一条
#: "redo"。它们不是用户做的编辑,栈往回走时要跳过而不是撤销 —— 撤销一条 "undo" 记录本身
#: 是没有意义的说法。
NOT_UNDOABLE: dict[str, str] = {
    "undo": "撤销栈自己的记账,不是一次编辑。往回找的时候跳过它。",
    "redo": "同上。",
}


def undoable(kind: str) -> Callable[[type], type]:
    """把一种操作的两个方向成对登记。重复登记视为编程错误,立刻报。"""

    def _decorator(pair: type) -> type:
        if kind in _REGISTRY:
            raise RuntimeError(f"undo pair for {kind!r} registered twice")
        if kind in NOT_UNDOABLE:
            raise RuntimeError(f"{kind!r} has an undo pair but is also listed in NOT_UNDOABLE")
        missing = [name for name in ("inverse", "forward") if not callable(getattr(pair, name, None))]
        if missing:
            raise RuntimeError(f"{kind!r} is missing {'/'.join(missing)}: both directions must be registered together")
        _REGISTRY[kind] = UndoPair(inverse=pair.inverse, forward=pair.forward)
        return pair

    return _decorator


def undoable_kinds() -> frozenset[str]:
    """可撤销的 kind —— 派生自注册表,不是另一份手写清单。"""
    return frozenset(_REGISTRY)


def is_bookkeeping(kind: str) -> bool:
    return kind in NOT_UNDOABLE


def apply_inverse(db: Session, sequence: Sequence, kind: str, payload: dict[str, Any]) -> None:
    _pair(kind).inverse(db, sequence, payload)


def apply_forward(db: Session, sequence: Sequence, kind: str, payload: dict[str, Any]) -> None:
    _pair(kind).forward(db, sequence, payload)


def _pair(kind: str) -> UndoPair:
    pair = _REGISTRY.get(kind)
    if pair is None:
        # 明确报错,而不是往回跳过这一条去撤销更早的编辑 —— 那会让用户丢掉一件他没打算撤销的事。
        raise SequenceDomainError("seqErr_notUndoable", kind=kind)
    return pair

