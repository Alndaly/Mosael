"""画板上产出者的**名字**(见 boards.producers)。

单独一个模块,因为画布校验(canvas)要认这些名字,而注册表本身依赖画布 —— 名字表不依赖任何人,
两边都从这里拿,才不会绕成一个环。
"""

from __future__ import annotations

from typing import Any

#: 内置产出者的名字。注册表里的四个与它一一对应(tests/test_board_producers.py 钉着)。
BUILTIN_PRODUCER_IDS = ("generate", "speak", "trim", "write")


def is_producer_id(value: Any) -> bool:
    """画布上存的 `form.producer` 是不是一个产出者的名字。**只认名字,不问现在能不能跑**:
    normalize 每次写入都过这一道,而一张板在某个产出者不可用时也得能开能存。"""
    return isinstance(value, str) and value in BUILTIN_PRODUCER_IDS
