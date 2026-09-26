"""画板上产出者的**名字**(见 boards.producers)。

单独一个模块,因为画布校验(canvas)要认这些名字,而注册表本身依赖画布 —— 名字表不依赖任何人,
两边都从这里拿,才不会绕成一个环。
"""

from __future__ import annotations

import re
from typing import Any

#: 内置产出者的名字。注册表里的几个与它一一对应(tests/test_board_producers.py 钉着)。
BUILTIN_PRODUCER_IDS = ("generate", "scene_render", "speak", "trim", "write")

#: 便签上的产出者:写字。新放下的便签、工具格交回的文字落成的便签都挂它(见下面的 SLOT_PRODUCERS、
#: canvas._derived_item)—— 放在这张名字表里,因为画布那一侧也要用,而它不能回头认识注册表。
NOTE_PRODUCER = "write"

#: 3D 场景格上的产出者:从场景的一个镜头渲出白模首尾帧 / 运镜视频(见 producers 的 scene_render)。
#: 此前这件事是一格单独的工具格(`node:scene_render`),和它引用的场景格是同一件事的两半 —— 现在渲染是
#: 场景格自己会做的事,和「剪一段」挂在视频 / 音频格上同一个样子。
SCENE_PRODUCER = "scene_render"

#: 产出**不落进宿主**、而是新建成宿主右边几格的内置产出者(ADR 0025 的 `landing: derived`)。工具格
#: (`node:*`)一律如此;内置的只有渲白模 —— 宿主是 3D 场景格,它的内容是那个场景(和缩略图),渲出来的
#: 首尾帧、运镜视频是右边新的几格,场景格一个字段不动。宿主的表单因此**就是**下一次运行发的那一份
#: (不会被产出清掉):智能体能照它替人点运行(见 derives_outputs 的用处)。
DERIVED_BUILTINS = frozenset({SCENE_PRODUCER})

#: 一种格子**还没有产出时**挂哪个产出者(新放下的一格的缺省):便签写字、音频念、图片/视频生成;
#: 3D 场景格挂渲白模(它的产出落在右边,
#: 场景格自己永远「还能再渲」);别的种类(分组框、文档、工具格)不在表里 —— 它们不是「等着被填」的槽。
#:
#: 放在这张无依赖的名字表里,因为画布校验(canvas.normalize_canvas)要照它补齐,而画布不能回头认识
#: 注册表(导入环)。它和注册表对得上 —— 表里的产出者挂得了那种格子、能挑来填空槽,能填空槽的产出者
#: 挂得了的每一种格子都在表里 —— 由 tests/test_board_producers.py 钉着。前端 api/domains/boards.ts 的 SLOT_PRODUCER 抄的是同一张。
SLOT_PRODUCERS: dict[str, str] = {
    "note": NOTE_PRODUCER, "image": "generate", "video": "generate", "audio": "speak", "scene": SCENE_PRODUCER,
}


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
    #: 媒体格的 asset_id 是它的产出:有了就不再是空槽。派生落点的宿主不一样 —— 3D 场景格的 asset_id 是
    #: 缩略图,不是渲出来的东西,有它照样挂渲白模。
    if kind != "note" and item.get("asset_id") and default not in DERIVED_BUILTINS:
        return None
    return default


def derives_outputs(item: dict[str, Any]) -> bool:
    """这一格跑出来的产出是**新建成右边的几格**(派生),而不是填进它自己。

    工具格(`action`)和挂着派生产出者的格子(3D 场景格渲白模)。画布那一侧(回执、摆占位、保存时保留
    服务端的状态)照它分两种落法 —— 派生的宿主自己的 asset_id 不是产出(场景格的缩略图),一概不动。
    """
    form = item.get("form") if isinstance(item.get("form"), dict) else {}
    return item.get("kind") == "action" or form.get("producer") in DERIVED_BUILTINS


def runs_from_draft(producer_id: Any) -> bool:
    """这个产出者的格子上存着的表单,就是一次运行发出去的那一份(工具格、场景格渲白模)。

    这种格子第二个入口(智能体的 set_form / run_board_item)能照原样替人填、替人点运行;内置的生成、写字、
    念、截的表单是各自面板的形状,拼成一次运行是面板的事(ADR 0021 P3)。
    """
    return isinstance(producer_id, str) and (node_type_of(producer_id) is not None or producer_id in DERIVED_BUILTINS)


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
