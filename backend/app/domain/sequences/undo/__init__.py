"""每种操作「怎么撤销 / 怎么重做」的注册表。

以前这是 history.py 里两条各 44 分支的 if/elif 阶梯,外加一份手写的 UNDOABLE_KINDS 元组 ——
同一件事分散在三个地方,而三者不同步时的表现全都很坏:

  - 漏进 UNDOABLE_KINDS:`_latest_undoable` 按 kind 过滤后取最新一条,于是它**跳过**刚做的那条,
    把更早的一条编辑撤了。200,没有报错,can_undo 一直是 true。用户按一次 ⌘Z 想撤销刚才的动作,
    消失的却是上一件不相干的编辑 —— 这是实测出来的,不是推演。
  - 漏进 _apply_inverse:要等到用户按下 ⌘Z 那一刻才炸。
  - 只写了逆向没写正向:撤销好使,重做时炸。

成对登记把这三种情况都变成结构上不可能:UNDOABLE_KINDS 由注册表**派生**而不是手写,而一个
kind 要么两个方向都有,要么根本不在表里。剩下的「记录了某种操作却没登记它的逆操作」由
tests/test_undo_registry.py 这道棘轮守着,例外写进 NOT_UNDOABLE 并说明理由。

登记方式(照 workflows/executors 那套):

    @undoable("trim_clip")
    class TrimClip:
        def inverse(db, sequence, payload): ...
        def forward(db, sequence, payload): ...
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
            raise RuntimeError(f"操作 {kind} 的逆操作重复注册")
        if kind in NOT_UNDOABLE:
            raise RuntimeError(f"操作 {kind} 既登记了逆操作又列在 NOT_UNDOABLE 里")
        missing = [name for name in ("inverse", "forward") if not callable(getattr(pair, name, None))]
        if missing:
            raise RuntimeError(f"操作 {kind} 缺少 {'/'.join(missing)} —— 两个方向必须成对")
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
        raise SequenceDomainError(f"「{kind}」这种操作不支持撤销")
    return pair


# 导入即注册:注册表定义完之后再挂载各实现模块(顺序无关,但保持稳定)。
from app.domain.sequences.undo import clips, properties, tracks  # noqa: E402,F401
