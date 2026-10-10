"""一张界面格式的图在智能体眼里是什么样(ADR 0042 §2):给 `comfy_canvas_read` 的那一份摘要,以及诊断、模板、节点包共用的
「图里有哪几层、节点叫什么」。

    {"op": "canvas_summary", "content": 界面格式的图}  → 每一层(根图、每一份子图定义)的节点:编号、类型、标题、控件的值、
                                                         谁连着谁、有哪些空间分组;子图在这张图里被哪几个节点用着、边界上有哪些口

**节点怎么指**:根图上的节点就是它的编号(`12`);子图里的节点用 ComfyUI 执行时的写法 —— 从根图往里走的节点号,冒号隔开
(`12:5` 是根图 12 号节点那个子图里面的 5 号)。工作台的「定位」(桥的 `locate`)认的就是这个写法,会先打开那一层。
一份子图定义被几个节点用着时,里面的节点按第一个用它的节点写,`instances` 里列全。

摘要不是原文:几百 KB 的界面格式(位置、大小、颜色、每一格的提示)智能体用不上,也装不下。长文字截短,节点太多只列前面的。
"""

from __future__ import annotations

from typing import Any

import convert
import node_catalog
from comfy_http import Comfy
from lines import ComfyError, say
from workflow_library import VIRTUAL_NODES, live_graph

#: 摘要里最多列多少个节点(各层加起来)。见过的最大的工作流两百来个。
MAX_NODES = 400
#: 控件里的一段文字最多留多少字(提示词;笔记节点的正文另算)。
MAX_TEXT = 400
#: 笔记节点(Note、MarkdownNote)最多留多少字:模板里的使用说明在里面,值得读。
MAX_NOTE = 1200
#: 子图套得再深也只走这么多层(坏文件可能套了它自己)。
MAX_DEPTH = 16
#: 只在前端的笔记节点:正文就是它唯一的 widget。
NOTE_TYPES = frozenset({"Note", "MarkdownNote"})
#: 子图边界上的两个虚拟节点(ComfyUI 前端的 SUBGRAPH_INPUT_ID / SUBGRAPH_OUTPUT_ID)。
SUBGRAPH_INPUT, SUBGRAPH_OUTPUT = -10, -20


def definitions(graph: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """子图定义:id → 那一份(套在定义里的定义也收)。"""
    found: dict[str, dict[str, Any]] = {}

    def collect(scope: dict[str, Any], depth: int) -> None:
        if depth > MAX_DEPTH:
            return
        for one in ((scope.get("definitions") or {}).get("subgraphs") or []):
            if isinstance(one, dict) and one.get("id") and str(one["id"]) not in found:
                found[str(one["id"])] = one
                collect(one, depth + 1)

    collect(graph, 0)
    return found


def nodes_of(scope: dict[str, Any]) -> list[dict[str, Any]]:
    return [node for node in scope.get("nodes") or [] if isinstance(node, dict) and node.get("id") is not None]


def groups_of(scope: dict[str, Any]) -> list[dict[str, Any]]:
    """这一层的空间分组。ComfyUI 原生分组按矩形覆盖节点,不另存节点成员。"""
    return [group for group in scope.get("groups") or [] if isinstance(group, dict)]


def _group(group: dict[str, Any], index: int) -> dict[str, Any] | None:
    bounding = group.get("bounding")
    if not isinstance(bounding, (list, tuple)) or len(bounding) < 4:
        pos, size = group.get("pos"), group.get("size")
        if not (isinstance(pos, (list, tuple)) and len(pos) >= 2 and isinstance(size, (list, tuple)) and len(size) >= 2):
            return None
        bounding = [pos[0], pos[1], size[0], size[1]]
    if not all(isinstance(value, (int, float)) for value in bounding[:4]):
        return None
    out: dict[str, Any] = {
        "ref": f"g{index + 1}",
        "title": str(group.get("title") or "Group")[:200],
        "position": [round(float(bounding[0]), 2), round(float(bounding[1]), 2)],
        "size": [round(float(bounding[2]), 2), round(float(bounding[3]), 2)],
    }
    if isinstance(group.get("color"), str) and group["color"]:
        out["color"] = group["color"][:20]
    return out


def instance_paths(graph: dict[str, Any]) -> dict[str, list[str]]:
    """每份子图定义在这张图里被哪几个节点用着:从根图往里走的节点号路径(`12`、`12:5`),按先后。"""
    defs = definitions(graph)
    found: dict[str, list[str]] = {}

    def walk(scope: dict[str, Any], prefix: str, depth: int) -> None:
        if depth > MAX_DEPTH:
            return
        for node in nodes_of(scope):
            kind = str(node.get("type") or "")
            if kind in defs:
                path = f"{prefix}{node['id']}"
                paths = found.setdefault(kind, [])
                if path not in paths and len(paths) < 50:
                    paths.append(path)
                    walk(defs[kind], f"{path}:", depth + 1)

    walk(graph, "", 0)
    return found


def class_types(graph: dict[str, Any]) -> set[str]:
    """图里用到的节点类型(各层),不含子图实例和只在前端的节点。"""
    defs = definitions(graph)
    found: set[str] = set()
    for scope in [graph, *defs.values()]:
        for node in nodes_of(scope):
            kind = str(node.get("type") or "")
            if kind and kind not in defs and kind not in VIRTUAL_NODES:
                found.add(kind)
    return found


def refs_by_type(graph: dict[str, Any]) -> dict[str, list[str]]:
    """每种节点类型在图里的哪几处(各层;子图里的按第一个用它的节点写,见模块说明)。不含子图实例和只在前端的节点。"""
    defs = definitions(graph)
    paths = instance_paths(graph)
    found: dict[str, list[str]] = {}
    scopes: list[tuple[dict[str, Any], str]] = [(graph, "")]
    scopes += [(one, f"{paths[key][0]}:") for key, one in defs.items() if key in paths]
    for scope, prefix in scopes:
        for node in nodes_of(scope):
            kind = str(node.get("type") or "")
            if kind and kind not in defs and kind not in VIRTUAL_NODES:
                found.setdefault(kind, []).append(f"{prefix}{node['id']}")
    return found


def locate_ref(graph: dict[str, Any], ref: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`12:5` → (那一层子图定义(根图上的是 None), 节点)。指不到 → (None, None)。"""
    defs = definitions(graph)
    parts = str(ref or "").split(":")
    scope: dict[str, Any] = graph
    layer: dict[str, Any] | None = None
    for depth, part in enumerate(parts):
        node = next((one for one in nodes_of(scope) if str(one["id"]) == part), None)
        if node is None:
            return None, None
        if depth == len(parts) - 1:
            return layer, node
        layer = defs.get(str(node.get("type") or ""))
        if layer is None:
            return None, None
        scope = layer
    return None, None


def _text(value: Any, limit: int) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"…(+{len(value) - limit})"
    return value


def _mode(node: dict[str, Any]) -> str:
    return {2: "muted", 4: "bypassed"}.get(node.get("mode"), "")


def _links(scope: dict[str, Any]) -> dict[str, tuple[Any, int, Any, int, Any]]:
    """连线 id(字符串)→ (源节点, 源槽, 目标节点, 目标槽, 类型)。数组、对象两种写法都认。"""
    return {str(key): value for key, value in convert._links(scope.get("links")).items()}  # noqa: SLF001 — 同一个插件


def _outputs_named(node: dict[str, Any], slot: int) -> str:
    outputs = [one for one in node.get("outputs") or [] if isinstance(one, dict)]
    if slot < len(outputs):
        return str(outputs[slot].get("name") or outputs[slot].get("type") or slot)
    return str(slot)


def _promoted(node: dict[str, Any], definition: dict[str, Any]) -> dict[str, Any]:
    """子图节点上提升出来的控件的值:按子图定义里是 widget 的那几格排(和 convert._from_subgraph_input 同一套认法)。"""
    declared = [one for one in definition.get("inputs") or [] if isinstance(one, dict)]
    entries = {one.get("name"): one for one in node.get("inputs") or [] if isinstance(one, dict) and one.get("name")}
    names = [one.get("name") for one in declared if entries.get(one.get("name")) is None or "widget" in entries[one.get("name")]]
    stored = node.get("widgets_values")
    if isinstance(stored, dict):
        return {str(name): _text(stored.get(name), MAX_TEXT) for name in names if stored.get(name) is not None}
    if not isinstance(stored, list):
        return {}
    return {str(name): _text(value, MAX_TEXT) for name, value in zip(names, stored) if value is not None}


def _node(node: dict[str, Any], scope: dict[str, Any], links: dict[str, Any], defs: dict[str, dict[str, Any]],
          object_info: dict[str, Any], prefix: str) -> dict[str, Any]:
    kind = str(node.get("type") or "")
    by_id = {str(one["id"]): one for one in nodes_of(scope)}
    out: dict[str, Any] = {"ref": f"{prefix}{node['id']}", "type": kind}
    pos = node.get("pos")
    if isinstance(pos, (list, tuple)) and len(pos) >= 2 and all(isinstance(value, (int, float)) for value in pos[:2]):
        out["position"] = [round(float(pos[0]), 2), round(float(pos[1]), 2)]
    size = node.get("size")
    if isinstance(size, (list, tuple)) and len(size) >= 2 and all(isinstance(value, (int, float)) for value in size[:2]):
        out["size"] = [round(float(size[0]), 2), round(float(size[1]), 2)]
    if node.get("title") and node.get("title") != kind:
        out["title"] = str(node["title"])[:200]
    if _mode(node):
        out["mode"] = _mode(node)
    if kind in defs:
        out.update(type="subgraph", subgraph=str(defs[kind].get("name") or kind)[:200], subgraph_id=kind)
        widgets = _promoted(node, defs[kind])
    elif kind in NOTE_TYPES:
        stored = node.get("widgets_values")
        widgets = {"text": _text(stored[0], MAX_NOTE)} if isinstance(stored, list) and stored else {}
    else:
        values = convert.widget_values(node, object_info) if kind in object_info else {}
        if not values and isinstance(node.get("widgets_values"), list):
            values = {str(index): value for index, value in enumerate(node["widgets_values"])}
        widgets = {name: _text(value, MAX_TEXT) for name, value in values.items()}
    linked: dict[str, str] = {}
    for entry in node.get("inputs") or []:
        if not isinstance(entry, dict) or entry.get("link") is None:
            continue
        link = links.get(str(entry["link"]))
        if link is None:
            continue
        origin, origin_slot = link[0], link[1]
        name = str(entry.get("name") or entry.get("label") or "")
        if str(origin) == str((scope.get("inputNode") or {}).get("id", SUBGRAPH_INPUT)):
            declared = [one for one in scope.get("inputs") or [] if isinstance(one, dict)]
            linked[name] = f"@in.{declared[origin_slot].get('name')}" if origin_slot < len(declared) else "@in"
        elif str(origin) in by_id:
            linked[name] = f"{prefix}{origin}.{_outputs_named(by_id[str(origin)], origin_slot)}"
        widgets.pop(name, None)  # 连了线的那一格不用存着的值
    if widgets:
        out["widgets"] = widgets
    if linked:
        out["in"] = linked
    return out


def summarize(content: dict[str, Any], object_info: dict[str, Any]) -> dict[str, Any]:
    """一张图的摘要(见模块说明)。`object_info` 只要图里那几类的(node_catalog.classes)。"""
    defs = definitions(content)
    paths = instance_paths(content)
    layers: list[dict[str, Any]] = []
    budget = MAX_NODES
    truncated = False
    scopes: list[tuple[dict[str, Any], dict[str, Any] | None]] = [(content, None)]
    scopes += [(one, one) for key, one in defs.items() if key in paths]
    for scope, definition in scopes:
        prefix = "" if definition is None else f"{paths[str(definition['id'])][0]}:"
        links = _links(scope)
        listed = nodes_of(scope)
        if len(listed) > budget:
            listed, truncated = listed[:budget], True
        budget -= len(listed)
        layer: dict[str, Any] = {"nodes": [_node(node, scope, links, defs, object_info, prefix) for node in listed]}
        groups = [shown for index, group in enumerate(groups_of(scope)) if (shown := _group(group, index)) is not None]
        if groups:
            layer["groups"] = groups
        if definition is None:
            layer["layer"] = "root"
        else:
            layer.update({
                "layer": "subgraph",
                "id": str(definition["id"]),
                "name": str(definition.get("name") or definition["id"])[:200],
                "instances": paths[str(definition["id"])],
                "inputs": [str(one.get("name")) for one in definition.get("inputs") or [] if isinstance(one, dict)],
                "outputs": [str(one.get("name")) for one in definition.get("outputs") or [] if isinstance(one, dict)],
            })
            fed = [f"{prefix}{link[0]}.{link[1]}" for link in links.values()
                   if str(link[2]) == str((scope.get("outputNode") or {}).get("id", SUBGRAPH_OUTPUT))]
            if fed:
                layer["outputs_from"] = fed
        layers.append(layer)
        if budget <= 0:
            truncated = truncated or len(scopes) > len(layers)
            break
    types = class_types(content)
    missing = sorted(kind for kind in types if kind not in object_info)
    node_count = sum(len(nodes_of(scope)) for scope, _ in scopes)
    return {"layers": layers, "missing_types": missing, "node_count": node_count, "truncated": truncated}


def canvas_summary(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """`{"op": "canvas_summary", "content"}`:画布上这张(或一张模板)的摘要。只问图里那几类节点的定义。"""
    content = live_graph(payload, locale)
    try:
        object_info = node_catalog.classes(comfy, class_types(content))
    except ComfyError as exc:
        raise ComfyError(say(locale, f"问不到这台 ComfyUI 的节点定义:{exc}", f"Couldn't read this ComfyUI's node definitions: {exc}")) from exc
    return summarize(content, object_info)


__all__ = ["MAX_NODES", "canvas_summary", "class_types", "definitions", "groups_of", "instance_paths", "locate_ref", "nodes_of", "refs_by_type",
           "summarize"]
