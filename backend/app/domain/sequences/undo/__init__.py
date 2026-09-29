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

from app.domain.sequences.undo.registry import (  # noqa: F401 —— 包的公开面不变
    NOT_UNDOABLE,
    Applier,
    UndoPair,
    _REGISTRY,
    _pair,
    apply_forward,
    apply_inverse,
    is_bookkeeping,
    undoable,
    undoable_kinds,
)

# 导入即注册:各模块只认 registry,不回头 import 这个包 —— 包和它的子模块之间就没有环了。
from app.domain.sequences.undo import clips, properties, tracks  # noqa: F401
