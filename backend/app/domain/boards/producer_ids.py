"""画板上产出者的**名字**(见 boards.producers)。

单独一个模块,因为画布校验(canvas)要认这些名字,而注册表本身依赖画布 —— 名字表不依赖任何人,
两边都从这里拿,才不会绕成一个环。
"""

from __future__ import annotations

import re
from typing import Any

#: 内置产出者的名字。注册表里的四个与它一一对应(tests/test_board_producers.py 钉着)。
BUILTIN_PRODUCER_IDS = ("generate", "speak", "trim", "write")

#: 便签上的产出者:写字。新放下的便签、工具格交回的文字落成的便签都挂它(见 producers.producer_for_new_slot、
#: canvas._derived_item)—— 放在这张名字表里,因为画布那一侧也要用,而它不能回头认识注册表。
NOTE_PRODUCER = "write"

#: 「跑一个工作流节点」的产出者:`node:<节点类型>`。节点类型是内置的(`text_transform`)或插件的
#: (`plugin.<包>.<工具>`,包名里有点号和连字符)。
NODE_PRODUCER_PREFIX = "node:"
_NODE_PRODUCER = re.compile(r"^node:[\w.\-]+$")


def is_producer_id(value: Any) -> bool:
    """画布上存的 `form.producer` 是不是一个产出者的名字。**只认名字,不问现在能不能跑**:
    normalize 每次写入都过这一道,而一张板在某个产出者不可用时(插件卸载了、连接删了)也得能开能存。"""
    if not isinstance(value, str):
        return False
    return value in BUILTIN_PRODUCER_IDS or bool(_NODE_PRODUCER.match(value))


def node_type_of(producer_id: str) -> str | None:
    """`node:<节点类型>` → 节点类型;不是节点产出者返回 None。"""
    if not isinstance(producer_id, str) or not _NODE_PRODUCER.match(producer_id):
        return None
    return producer_id[len(NODE_PRODUCER_PREFIX) :]


def node_producer_id(node_type: str) -> str:
    return f"{NODE_PRODUCER_PREFIX}{node_type}"
