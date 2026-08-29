"""创意画板的细粒度编辑。

智能体表达的是**意图**(加一张便签、把这两项连起来、把这段文字改掉),由服务端落到当前画布 ——
而不是让它重写整份 canvas。后者在稍微复杂一点的画板上必然出错:模型要么漏掉几项、要么把
用户刚拖好的位置全部推平,而这两种错都不会报错,只会让用户发现"我的东西不见了"。

算子按顺序作用在一份副本上,所以 add_item → connect 放在同一批里就能用(后面的算子看得见
前面新加的项)。产物不在这里校验 —— 交给 normalize_canvas,它才是"存得下、读得回"的那道关。
"""

from __future__ import annotations

import copy
from typing import Any

from app.domain.boards import ITEM_KINDS, NOTE_COLORS, BoardDomainError

BOARD_OP_KINDS = (
    "add_item",
    "set_text",
    "set_color",
    "move_item",
    "resize_item",
    "remove_item",
    "connect",
    "remove_edge",
)

#: 新建时的默认大小。**和前端 DEFAULT_SIZE 是同一组数** —— 智能体加的项不该比手动加的
#: 小一圈,那看起来像两种不同的东西。
DEFAULT_SIZE: dict[str, tuple[int, int]] = {
    "note": (220, 140),
    "image": (260, 180),
    "video": (320, 200),
    "audio": (280, 72),
    "frame": (420, 300),
}


def _require(by_id: dict[str, dict], item_id: str) -> dict:
    item = by_id.get(item_id)
    if item is None:
        raise BoardDomainError(f"画板项不存在:{item_id or '(空)'}")
    return item


def _number(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise BoardDomainError(f"{field} 必须是数字,收到 {value!r}")
    return float(value)


def apply_board_ops(canvas: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    """把算子作用到 `canvas` 的副本上,返回新画布(**未校验**)。

    算子本身不合法(未知种类、指向不存在的项)时抛 BoardDomainError。调用方在落库前
    要过一遍 normalize_canvas。
    """
    board = copy.deepcopy(canvas or {})
    items: list[dict] = board.setdefault("items", [])
    edges: list[dict] = board.setdefault("edges", [])
    by_id: dict[str, dict] = {str(one.get("id")): one for one in items}

    def gen_id(kind: str) -> str:
        index = 1
        while f"{kind}_{index}" in by_id:
            index += 1
        return f"{kind}_{index}"

    def next_position() -> tuple[float, float]:
        #: 摆在最右边那一项的右边。摞在原点上的话,智能体加三项就是三张叠在一起的卡片。
        right = max((float(one.get("x", 0)) + float(one.get("width", 0)) for one in items), default=0.0)
        return (right + 60.0 if items else 80.0, 120.0)

    for op in operations:
        if not isinstance(op, dict):
            raise BoardDomainError("算子必须是对象")
        kind = str(op.get("kind", ""))

        if kind == "add_item":
            item_kind = str(op.get("type", ""))
            if item_kind not in ITEM_KINDS:
                raise BoardDomainError(f"未知的画板项类型:{item_kind};可用的是 {'、'.join(ITEM_KINDS)}")
            item_id = str(op.get("item_id") or "").strip() or gen_id(item_kind)
            if item_id in by_id:
                raise BoardDomainError(f"画板项 id 重复:{item_id}")
            width, height = DEFAULT_SIZE[item_kind]
            default_x, default_y = next_position()
            item: dict[str, Any] = {
                "id": item_id,
                "kind": item_kind,
                "x": _number(op["x"], "x") if op.get("x") is not None else default_x,
                "y": _number(op["y"], "y") if op.get("y") is not None else default_y,
                "width": _number(op["width"], "width") if op.get("width") is not None else float(width),
                "height": _number(op["height"], "height") if op.get("height") is not None else float(height),
            }
            if op.get("text") is not None:
                item["text"] = str(op["text"])
            if op.get("color") is not None:
                item["color"] = str(op["color"])
            if op.get("asset_id"):
                item["asset_id"] = str(op["asset_id"])
            items.append(item)
            by_id[item_id] = item

        elif kind == "set_text":
            _require(by_id, str(op.get("item_id", "")))["text"] = str(op.get("text", ""))

        elif kind == "set_color":
            color = str(op.get("color", ""))
            if color not in NOTE_COLORS:
                raise BoardDomainError(f"未知的颜色:{color};可用的是 {'、'.join(NOTE_COLORS)}")
            _require(by_id, str(op.get("item_id", "")))["color"] = color

        elif kind == "move_item":
            item = _require(by_id, str(op.get("item_id", "")))
            item["x"] = _number(op.get("x"), "x")
            item["y"] = _number(op.get("y"), "y")

        elif kind == "resize_item":
            item = _require(by_id, str(op.get("item_id", "")))
            for field in ("width", "height"):
                if op.get(field) is not None:
                    size = _number(op[field], field)
                    if size <= 0:
                        raise BoardDomainError(f"{field} 必须大于 0")
                    item[field] = size

        elif kind == "remove_item":
            item_id = str(op.get("item_id", ""))
            _require(by_id, item_id)
            items[:] = [one for one in items if str(one.get("id")) != item_id]
            by_id.pop(item_id, None)
            #: 连着它的线一起去掉 —— 留着的话 normalize_canvas 会拒绝整份画布(悬空的线),
            #: 于是一次"删掉这张图"变成一句看不懂的报错。
            edges[:] = [
                edge
                for edge in edges
                if str(edge.get("source")) != item_id and str(edge.get("target")) != item_id
            ]

        elif kind == "connect":
            source = str(op.get("source", ""))
            target = str(op.get("target", ""))
            _require(by_id, source)
            _require(by_id, target)
            if source == target:
                raise BoardDomainError("不能把一项连到它自己")
            edge_id = str(op.get("edge_id") or "").strip() or f"e-{source}-{target}"
            if any(str(edge.get("id")) == edge_id for edge in edges):
                continue  # 已经连过了,重复一次不是错
            edges.append({"id": edge_id, "source": source, "target": target})

        elif kind == "remove_edge":
            edge_id = str(op.get("edge_id", ""))
            if not any(str(edge.get("id")) == edge_id for edge in edges):
                raise BoardDomainError(f"连线不存在:{edge_id or '(空)'}")
            edges[:] = [edge for edge in edges if str(edge.get("id")) != edge_id]

        else:
            raise BoardDomainError(f"不支持的画板算子:{kind or '(空)'}")

    return board
