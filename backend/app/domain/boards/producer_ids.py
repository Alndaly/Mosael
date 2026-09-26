"""画板上产出者的**名字**(见 boards.producers)。

单独一个模块,因为画布校验(canvas)要认这些名字,而注册表本身依赖画布 —— 名字表不依赖任何人,
两边都从这里拿,才不会绕成一个环。
"""

from __future__ import annotations

import re
from typing import Any

#: 内置产出者的名字。注册表里的四个与它一一对应(tests/test_board_producers.py 钉着)。
BUILTIN_PRODUCER_IDS = ("generate", "speak", "trim", "write")

#: 便签上的产出者:写字。新放下的便签、工具格交回的文字落成的便签都挂它(见下面的 SLOT_PRODUCERS、
#: canvas._derived_item)—— 放在这张名字表里,因为画布那一侧也要用,而它不能回头认识注册表。
NOTE_PRODUCER = "write"

#: 一种格子**还没有产出时**挂哪个产出者(新放下的一格的缺省):便签写字、音频念、图片/视频生成;
#: 别的种类(分组框、3D 场景、文档、工具格)不在表里 —— 它们不是「等着被填」的槽。
#:
#: 放在这张无依赖的名字表里,因为画布校验(canvas.normalize_canvas)要照它补齐,而画布不能回头认识
#: 注册表(导入环)。它和注册表对得上 —— 表里的产出者挂得了那种格子、能挑来填空槽,能填空槽的产出者
#: 挂得了的每一种格子都在表里 —— 由 tests/test_board_producers.py 钉着。前端 api/domains/boards.ts 的 SLOT_PRODUCER 抄的是同一张。
SLOT_PRODUCERS: dict[str, str] = {"note": NOTE_PRODUCER, "image": "generate", "video": "generate", "audio": "speak"}


def missing_slot_producer(item: dict[str, Any]) -> str | None:
    """这一格**该写明却没写明**的产出者;不缺(或它不是一个能产出的槽)回 None。

    「能产出、还没产出」的一格(空的图片/视频/音频槽;便签 —— 它的产出是自己的正文,有字照样能让 AI
    改)必须写明产出者,面板照它挂(见前端 boardItemState.producerOf)。缺了的按 SLOT_PRODUCERS 补。
    已经写明了的一律不动 —— 写进去之后它就是那一格自己的事实(音频槽可以从念切到生成;截取那一格由
    服务端摆占位时写明 `trim`,见 actions._pending)。
    """
    kind = item.get("kind")
    default = SLOT_PRODUCERS.get(kind) if isinstance(kind, str) else None
    form = item.get("form") if isinstance(item.get("form"), dict) else {}
    if default is None or form.get("producer") is not None:
        return None
    if kind != "note" and item.get("asset_id"):
        return None
    return default


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
