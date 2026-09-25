"""创意画板的细粒度编辑。

智能体表达的是**意图**(加一张便签、把这两项连起来、把这段文字改掉),由服务端落到当前画布 ——
而不是让它重写整份 canvas。后者在稍微复杂一点的画板上必然出错:模型要么漏掉几项、要么把
用户刚拖好的位置全部推平,而这两种错都不会报错,只会让用户发现"我的东西不见了"。

算子按顺序作用在一份副本上,所以 add_item → connect 放在同一批里就能用(后面的算子看得见
前面新加的项)。产物不在这里校验 —— 交给 normalize_canvas,它才是"存得下、读得回"的那道关。

工具格(`action`)的表单也由算子写:`add_item` 带上 producer/config/bindings,`set_form` 改它。
这里只管**形状**(是个工具、是个对象);「这个人有没有这个工具、绑定接得上吗、字段对不对」要看
注册表和整张画布,由调用方在落库之前问 boards.producers.check_forms(见智能体的 edit_board)。
"""

from __future__ import annotations

import copy
from typing import Any

from app.domain.boards.canvas import DEFAULT_SIZE, ITEM_KINDS, NOTE_COLORS, BoardDomainError, finite_number, item_not_found
from app.domain.boards.producer_ids import node_type_of

BOARD_OP_KINDS = (
    "add_item",
    "set_title",
    "set_text",
    "set_color",
    "move_item",
    "resize_item",
    "remove_item",
    "connect",
    "remove_edge",
    "set_form",
)

#: 算子上写工具格表单的那三样(和画布上 `form` 里的键同名)。
_FORM_KEYS = ("producer", "config", "bindings")


def _tool_form(op: dict[str, Any], current: dict[str, Any], item_id: str) -> dict[str, Any]:
    """按算子写一格工具格的表单:`{"config", "bindings", "producer"}`(产出者排最后,和 actions._pending 一致)。

    · `producer` 只能是一个工具(`node:<节点类型>`)。内置的写字 / 生成 / 念 / 截的表单是各自面板的
      形状,由用户在面板上填;替他写一份面板不认的表单,只会让面板打不开。
    · 换了工具,旧的 config / bindings 属于上一个工具,一并清掉。
    · 同一个工具:`config` **逐键合并**(值为 null = 删掉这个键),`bindings` **逐字段替换**
      (空列表或 null = 这个字段不再接上游)—— 改一个字段不必把整张表单抄一遍。
    """
    producer = op.get("producer", current.get("producer"))
    if node_type_of(str(producer or "")) is None:
        raise BoardDomainError("boardErr_formNeedsTool", item_id=item_id, producer=str(producer or ""))
    same = producer == current.get("producer")
    config = dict(current.get("config") or {}) if same else {}
    bindings = dict(current.get("bindings") or {}) if same else {}
    for key, into in (("config", config), ("bindings", bindings)):
        patch = op.get(key)
        if patch is None:
            continue
        if not isinstance(patch, dict):
            raise BoardDomainError("boardErr_itemFieldNotObject", item_id=item_id, field=f"form.{key}")
        for field, value in patch.items():
            if value is None or (key == "bindings" and value == []):
                into.pop(field, None)
            else:
                into[field] = value
    return {"config": config, "bindings": bindings, "producer": producer}


def _require(by_id: dict[str, dict], item_id: str) -> dict:
    item = by_id.get(item_id)
    if item is None:
        raise item_not_found(item_id)
    return item


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
            raise BoardDomainError("boardErr_opNotObject")
        kind = str(op.get("kind", ""))

        if kind == "add_item":
            item_kind = str(op.get("type", ""))
            if item_kind not in ITEM_KINDS:
                raise BoardDomainError("boardErr_unknownItemKind", kind=item_kind, kinds=", ".join(ITEM_KINDS))
            item_id = str(op.get("item_id") or "").strip() or gen_id(item_kind)
            if item_id in by_id:
                raise BoardDomainError("boardErr_duplicateItemId", item_id=item_id)
            width, height = DEFAULT_SIZE[item_kind]
            default_x, default_y = next_position()
            item: dict[str, Any] = {
                "id": item_id,
                "kind": item_kind,
                "x": finite_number(op["x"], "x") if op.get("x") is not None else default_x,
                "y": finite_number(op["y"], "y") if op.get("y") is not None else default_y,
                "width": finite_number(op["width"], "width") if op.get("width") is not None else float(width),
                "height": finite_number(op["height"], "height") if op.get("height") is not None else float(height),
            }
            if op.get("title") is not None:
                item["title"] = str(op["title"])
            if op.get("text") is not None:
                item["text"] = str(op["text"])
            if op.get("color") is not None:
                item["color"] = str(op["color"])
            if item_kind == "document" and op.get("note_id"):
                item["note_id"] = op["note_id"]
                item["note_revision"] = op.get("note_revision")
            if op.get("scene_id"):
                item["scene_id"] = str(op["scene_id"])
            if item_kind == "action":
                #: 工具格就是「跑哪个工具」—— 没有工具的一格什么也做不了,不放。
                item["form"] = _tool_form(op, {}, item_id)
            elif any(op.get(key) is not None for key in _FORM_KEYS):
                raise BoardDomainError("boardErr_formOnlyOnAction", item_id=item_id, kind=item_kind)
            elif op.get("asset_id"):
                item["asset_id"] = str(op["asset_id"])
            else:
                #: 还没有产出的一格(便签、空的图片/视频/音频槽)写明它的产出者 —— 面板照它挂,
                #: 和手动放下的一格同一个样子(见 producers.producer_for_new_slot)。
                from app.domain.boards.producers import producer_for_new_slot

                producer = producer_for_new_slot(item_kind)
                if producer:
                    item["form"] = {"producer": producer}
            items.append(item)
            by_id[item_id] = item

        elif kind == "set_title":
            #: 给一格起名 / 改名。空串 = 不要名字了,退回显示种类名。长度和空白由 normalize 管。
            item = _require(by_id, str(op.get("item_id", "")))
            title = str(op.get("title") or "")
            if title.strip():
                item["title"] = title
            else:
                item.pop("title", None)

        elif kind == "set_form":
            #: 改工具格的表单:换工具、改配置、改哪些字段接上游。只对工具格 —— 别的格子的表单归面板。
            item_id = str(op.get("item_id", ""))
            item = _require(by_id, item_id)
            if item.get("kind") != "action":
                raise BoardDomainError("boardErr_formOnlyOnAction", item_id=item_id, kind=str(item.get("kind")))
            item["form"] = _tool_form(op, dict(item.get("form") or {}), item_id)

        elif kind == "set_text":
            _require(by_id, str(op.get("item_id", "")))["text"] = str(op.get("text", ""))

        elif kind == "set_color":
            color = str(op.get("color", ""))
            if color not in NOTE_COLORS:
                raise BoardDomainError("boardErr_unknownColor", color=color, colors=", ".join(NOTE_COLORS))
            _require(by_id, str(op.get("item_id", "")))["color"] = color

        elif kind == "move_item":
            item = _require(by_id, str(op.get("item_id", "")))
            item["x"] = finite_number(op.get("x"), "x")
            item["y"] = finite_number(op.get("y"), "y")

        elif kind == "resize_item":
            item = _require(by_id, str(op.get("item_id", "")))
            for field in ("width", "height"):
                if op.get(field) is not None:
                    size = finite_number(op[field], field)
                    if size <= 0:
                        raise BoardDomainError("boardErr_sizeNotPositive", field=field)
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
                raise BoardDomainError("boardErr_selfEdge")
            edge_id = str(op.get("edge_id") or "").strip() or f"e-{source}-{target}"
            #: 已经连过了,重复一次不是错。**按「哪两项」认,不只按 id** —— 画布上手拉的线 id 是
            #: React Flow 起的,只按 id 查的话同一对会多出第二根,下游拿上游文字时被拼进提示词两遍。
            if any(
                str(edge.get("id")) == edge_id
                or (str(edge.get("source")) == source and str(edge.get("target")) == target)
                for edge in edges
            ):
                continue
            edges.append({"id": edge_id, "source": source, "target": target})

        elif kind == "remove_edge":
            edge_id = str(op.get("edge_id", ""))
            if not any(str(edge.get("id")) == edge_id for edge in edges):
                if not edge_id:
                    raise BoardDomainError("boardErr_edgeIdMissing")
                raise BoardDomainError("boardErr_edgeNotFound", edge_id=edge_id)
            edges[:] = [edge for edge in edges if str(edge.get("id")) != edge_id]

        else:
            if not kind:
                raise BoardDomainError("boardErr_opKindMissing")
            raise BoardDomainError("boardErr_unknownOp", kind=kind)

    return board
