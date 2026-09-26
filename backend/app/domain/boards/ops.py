"""创意画板的细粒度编辑。

智能体表达的是**意图**(加一张便签、把这两项连起来、把这段文字改掉),由服务端落到当前画布 ——
而不是让它重写整份 canvas。后者在稍微复杂一点的画板上必然出错:模型要么漏掉几项、要么把
用户刚拖好的位置全部推平,而这两种错都不会报错,只会让用户发现"我的东西不见了"。

算子按顺序作用在一份副本上,所以 add_item → connect 放在同一批里就能用(后面的算子看得见
前面新加的项)。产物不在这里校验 —— 交给 normalize_canvas,它才是"存得下、读得回"的那道关。

画板上没有单独的工具格:把内容变成新内容的工具是内容格自己的**能力**(ADR 0025 修订)。它们的设置也由算子写 ——
`set_form` 带上 `ability: true` 写进那一格的 `form.abilities[producer]`(调用方按注册表判它是不是一项能力,
见智能体的 edit_board)。一格**自己**的表单只在它存着的就是一次运行发的那一份时才由算子写
(producer_ids.runs_from_draft):空格子上的生成器(`node:*`)、3D 场景格渲白模(`scene_render`,只有 config)。
这里只管**形状**(是个节点产出者、是个对象);「这个人有没有这个工具、绑定接得上吗、字段对不对」要看
注册表和整张画布,由调用方在落库之前问 boards.producers.check_forms(见智能体的 edit_board)。
"""

from __future__ import annotations

import copy
from typing import Any

from app.domain.boards.canvas import DEFAULT_SIZE, ITEM_KINDS, NOTE_COLORS, BoardDomainError, finite_number, item_not_found
from app.domain.boards.producer_ids import SLOT_PRODUCERS, node_type_of, runs_from_draft

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

#: 算子上写表单的那三样(和画布上 `form` 里的键同名)。
_FORM_KEYS = ("producer", "config", "bindings")


def _merged(op: dict[str, Any], current: dict[str, Any], item_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """`config` **逐键合并**(值为 null = 删掉这个键),`bindings` **逐字段替换**(空列表或 null = 这个字段不再接
    上游)—— 改一个字段不必把整张表单抄一遍。"""
    config = dict(current.get("config") or {})
    bindings = dict(current.get("bindings") or {})
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
    return config, bindings


def _own_form(op: dict[str, Any], current: dict[str, Any], item_id: str) -> dict[str, Any]:
    """按算子写一格**自己**的表单:`{"config", "bindings", "producer"}`(产出者排最后,和 actions._pending 一致)。

    · `producer` 只能是一个节点产出者(`node:<节点类型>`,空格子上的生成器),或 3D 场景格的渲白模
      (`scene_render`,只有 config)。内置的写字 / 生成 / 念 / 截的表单是各自面板的形状,由用户在面板上填;
      替他写一份面板不认的表单,只会让面板打不开。
    · 换了产出者,旧的 config / bindings 属于上一个,一并清掉;能力的设置(`abilities`)归这一格,留着。
    """
    producer = op.get("producer", current.get("producer"))
    if not runs_from_draft(producer):
        raise BoardDomainError("boardErr_formNeedsTool", item_id=item_id, producer=str(producer or ""))
    if node_type_of(str(producer)) is None:
        #: 内置的那个(场景格渲白模)没有接上游的字段:镜头、渲什么都直接填。
        field = next(iter(op.get("bindings") or {}), None)
        if field is not None:
            raise BoardDomainError("boardErr_bindingFieldNotBindable", tool=str(producer), field=str(field))
    same = producer == current.get("producer")
    config, bindings = _merged(op, current if same else {}, item_id)
    kept = {"abilities": current["abilities"]} if current.get("abilities") else {}
    if node_type_of(str(producer)) is None:
        return {"config": config, **kept, "producer": producer}
    return {"config": config, "bindings": bindings, **kept, "producer": producer}


def _ability_form(op: dict[str, Any], current: dict[str, Any], item_id: str) -> dict[str, Any]:
    """按算子写一格的一项**能力**的设置:`form.abilities[producer] = {"config", "bindings"}`,合并规矩同上。
    这一格自己的产出者和别的几项能力的设置不动;`abilities` 排在产出者前面(和 canvas._with_ability 一致)。"""
    producer = op.get("producer")
    if node_type_of(str(producer or "")) is None:
        raise BoardDomainError("boardErr_formNeedsTool", item_id=item_id, producer=str(producer or ""))
    form = {key: value for key, value in current.items() if key != "producer"}
    abilities = dict(form.pop("abilities", None) or {})
    config, bindings = _merged(op, abilities.get(str(producer)) or {}, item_id)
    abilities[str(producer)] = {"config": config, "bindings": bindings}
    own = {"producer": current["producer"]} if current.get("producer") is not None else {}
    return {**form, "abilities": abilities, **own}


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
            if item_kind in SLOT_PRODUCERS and any(op.get(key) is not None for key in _FORM_KEYS):
                #: 带着表单放下一格:空格子上的生成器、3D 场景格渲白模的设置(产出者缺省就是这种格子挂的那一个)。
                item["form"] = _own_form(op, {"producer": SLOT_PRODUCERS[item_kind]}, item_id)
            elif any(op.get(key) is not None for key in _FORM_KEYS):
                raise BoardDomainError("boardErr_formNotOnKind", item_id=item_id, kind=item_kind)
            elif op.get("asset_id"):
                item["asset_id"] = str(op["asset_id"])
            #: 还没有产出的一格(便签、空的图片/视频/音频槽)写明产出者这件事**不在这里做**:画布的每一次
            #: 写入都过 normalize_canvas,由它照 producer_ids.SLOT_PRODUCERS 补齐 —— 一条规则、一处。
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
            #: 写一格的一项能力的设置(`ability`),或这一格自己的表单(空格子上换生成器、改它的配置;3D 场景格上
            #: 改渲白模的设置)。别的表单归面板。
            item_id = str(op.get("item_id", ""))
            item = _require(by_id, item_id)
            kind = str(item.get("kind"))
            current = dict(item.get("form") or {})
            if op.get("ability"):
                item["form"] = _ability_form(op, current, item_id)
                continue
            if kind not in SLOT_PRODUCERS:
                raise BoardDomainError("boardErr_formNotOnKind", item_id=item_id, kind=kind)
            current.setdefault("producer", SLOT_PRODUCERS[kind])
            item["form"] = _own_form(op, current, item_id)

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
