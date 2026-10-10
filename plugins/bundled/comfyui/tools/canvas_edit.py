"""改画布上这张(ADR 0042 §2 的 `applyOps`、§6 子图怎么改)—— 插件这一侧:一批改动先对着这张图和这台 ComfyUI 的节点定义校验,
在一份拷贝上照着改一遍,得出交给画布的桥的那一批(规整过的)、给人看的改动清单、改前改后各一次诊断。

    {"op": "edit_plan", "content": 画布上这张, "ops": [...]}
        → {"ops": 交给桥的那一批, "changes": 改动清单(结构化,界面按读的人的语言说), "subgraphs": 改了哪几份子图定义、各用了几处,
           "check": {"before", "after", "fixed", "introduced", "baseline": 改之前那一份问题单}, "structural": 有没有打包 / 拆开}

**智能体写的改动**(每一条一个 `op`;节点按画布摘要的写法指:`12`,子图里的 `12:5` —— 改的是那份子图的**定义**,这张图里所有
用它的地方一起变):

    add_node {id: "$a", type, widgets?, title?, near?, graph?}   加一个节点;`$a` 是这一批里叫它的临时名字
    remove_node {node}                                           删掉(连着的线一起断)
    connect {from: "<节点>.<输出名>" | "@in.<口>", to: "<节点>.<输入名>" | "@out.<口>"}   按名字连,不按槽位号
    disconnect {to: "<节点>.<输入名>" | "@out.<口>"}               断开接进这一格的那根线
    set_widget {node, widget, value}                              改一格控件(子图节点上提升出来的那几格也是这样改)
    set_title {node, title}
    set_position {node, x, y}                                    移动节点到画布绝对坐标
    add_group {title, x, y, width, height, color?, graph?}        新建空间分组;节点落在矩形里就属于它
    set_group {group, title?, x?, y?, width?, height?, color?}    重命名 / 移动 / 缩放分组(`group` 用摘要里的 g1)
    remove_group {group}                                         删除分组(不删除里面的节点)
    bypass / mute {node, on?}                                     旁路 / 静音(on: false 恢复成正常)
    add_subgraph_input / add_subgraph_output {graph, name, type}  子图边界上加一个口,用它的节点跟着多一个
    remove_subgraph_io {graph, name, side?}                       删掉一个口(里外连着的线一起断)
    promote_widget / unpromote_widget {node, widget}              把子图里一格控件提到外面那个节点上 / 收回去
    to_subgraph {nodes, name?}                                    把同一层的几个节点打包成一个子图
    unpack_subgraph {node}                                        把一个子图节点拆回原样

`graph` 指哪一层:从根图往里走的节点号(`"12"`、`"12:5"`,或者写成 `["12", "5"]`),或者子图定义的 id。带 `node` 的那几条也可以
给 `graph`,那时 `node` 写那一层里的编号。

**交给桥的那一批**:每条带 `layer`(根图是 null,子图是定义的 id),节点都是那一层里的编号;新节点仍用临时名字(桥建出来才有
编号),输入输出仍按名字(桥自己对槽位)。桥照这一批再查一遍才动画布,一批只占一步撤销(见 electron 的 comfyWorkbench)。

**提升控件**照前端自己的做法(1.53 的 promoteValueWidgetViaSubgraphInput):子图边界上加一个同名的输入口(重名就加 `_1`),
接到里面那一格 —— 用这份子图的节点上就多出那一格控件,值先照里面那一格。

**打包、拆开**改的是结构、不改算什么:这里不模拟(节点号由前端排),只查节点在不在、是不是同一层,而且只能放在这一批的最后
—— 后面的改动指不到打包以后的节点。
"""

from __future__ import annotations

import copy
import math
import re
import uuid
from typing import Any

import canvas
import convert
import diagnose
import node_catalog
from comfy_http import Comfy
from lines import ComfyError, say
from workflow_import import _type_of
from workflow_library import _choices, live_graph

#: 一批最多几条(再多就该拆成几批,或者从模板开始)。
MAX_OPS = 200
#: 说不通的最多列几条(多了智能体也看不过来;改了前面的,后面的往往跟着好了)。
MAX_PROBLEMS = 20
#: 一格控件的值最多多长(提示词)。
MAX_VALUE = 20000
MAX_COORDINATE = 1_000_000
_PATH = re.compile(r"^-?\d{1,10}(?::\d{1,10}){0,16}$")
_LOCAL = re.compile(r"^-?\d{1,10}$")
_SUBGRAPH_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_TEMP = re.compile(r"^\$[A-Za-z0-9_]{1,32}$")
_NAME = re.compile(r"^[^\x00-\x1f]{1,100}$")
_GROUP_REF = re.compile(r"^g([1-9]\d*)$")
_COLOR = re.compile(r"^#[0-9A-Fa-f]{3}(?:[0-9A-Fa-f]{3})?$")
_MODES = {"bypass": 4, "mute": 2}
_MODE_NAMES = {0: "normal", 2: "muted", 4: "bypassed"}
#: 只在前端、但能加的节点:笔记(正文是它唯一的那一格)。
_NOTES = canvas.NOTE_TYPES
#: 改之前那一份问题单每条留哪几样(应用之后对着它说修好了哪几个,见 diagnose.compare)。
_BASELINE_KEYS = ("ref", "type", "title", "severity", "kind", "input", "cause")
#: 只改结构的两种(不模拟,只能放在最后)。
STRUCTURAL = ("to_subgraph", "unpack_subgraph")
OPS = ("add_node", "remove_node", "connect", "disconnect", "set_widget", "set_title", "set_position", "add_group", "set_group", "remove_group",
       "bypass", "mute", "add_subgraph_input",
       "add_subgraph_output", "remove_subgraph_io", "promote_widget", "unpromote_widget", *STRUCTURAL)


class _Bad(Exception):
    """这一条说不通。两种语言都带着,最后合成一句交给宿主。"""

    def __init__(self, zh: str, en: str) -> None:
        super().__init__(en)
        self.zh = zh
        self.en = en


def _str(value: Any, limit: int = 200) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _link_id(link: Any) -> str:
    if isinstance(link, list) and link:
        return str(link[0])
    if isinstance(link, dict):
        return str(link.get("id"))
    return ""


class _Planner:
    """在一份拷贝上照着改,边改边记交给桥的那一条和给人看的那一条。"""

    def __init__(self, content: dict[str, Any], object_info: dict[str, Any]) -> None:
        self.graph = copy.deepcopy(content)
        self.info = object_info
        self.defs = canvas.definitions(self.graph)
        self._normalize_collections()
        #: 每份子图在这张图里被哪几个节点用着(改之前的;改动清单上说「用了 N 处」、子图里的节点按第一处写)
        self.paths = canvas.instance_paths(content)
        self.temps: dict[str, tuple[str | None, dict[str, Any]]] = {}
        self.group_refs: dict[tuple[str | None, str], dict[str, Any]] = {}
        for layer in [None, *self.defs]:
            for index, group in enumerate(canvas.groups_of(self.scope(layer))):
                self.group_refs[(layer, f"g{index + 1}")] = group
        self.node_seq = self._max_id("nodes") + 1
        self.link_seq = self._max_id("links") + 1
        self.group_seq = self._max_id("groups") + 1
        self.bridge: list[dict[str, Any]] = []
        self.changes: list[dict[str, Any]] = []
        self.touched: list[str] = []
        self.structural = False

    def _normalize_collections(self) -> None:
        """把 ComfyUI 界面图里 ``list | null`` 的集合规整成可编辑的列表。

        当前保存格式会把未接线的输出写成 ``{"links": null}``，接上线以后同一字段才是数组。
        读图时两者都表示“没有线”；规划器要接第一根线时必须先落成数组。这里只改深拷贝，
        不改桥交来的原图。
        """
        for scope in [self.graph, *self.defs.values()]:
            for key in ("nodes", "links", "groups"):
                if scope.get(key) is None:
                    scope[key] = []
            for node in canvas.nodes_of(scope):
                for key in ("inputs", "outputs"):
                    if node.get(key) is None:
                        node[key] = []
                for output in node.get("outputs") or []:
                    if isinstance(output, dict) and output.get("links") is None:
                        output["links"] = []
            # 子图边界的 linkIds 也使用同一套 list | null 表示法。
            for side in ("inputs", "outputs"):
                for slot in scope.get(side) or []:
                    if isinstance(slot, dict) and slot.get("linkIds") is None:
                        slot["linkIds"] = []

    # --- 哪一层、哪个节点 -----------------------------------------------------------------

    def _scopes(self) -> list[dict[str, Any]]:
        return [self.graph, *self.defs.values()]

    def _max_id(self, what: str) -> int:
        found = [0]
        for scope in self._scopes():
            items = scope.get(what) or []
            for one in items:
                raw = one.get("id") if isinstance(one, dict) else (one[0] if isinstance(one, list) and one else None)
                try:
                    found.append(int(raw))
                except (TypeError, ValueError):
                    continue
            state = scope.get("state") if isinstance(scope.get("state"), dict) else {}
            state_keys = (("last_node_id", "lastNodeId") if what == "nodes"
                          else ("last_link_id", "lastLinkId") if what == "links" else ())
            for key in state_keys:
                value = scope.get(key) if key.startswith("last_") else state.get(key)
                if isinstance(value, int):
                    found.append(value)
        return max(found)

    def scope(self, layer: str | None) -> dict[str, Any]:
        return self.graph if layer is None else self.defs[layer]

    @staticmethod
    def _find(scope: dict[str, Any], local: str) -> dict[str, Any] | None:
        return next((one for one in canvas.nodes_of(scope) if str(one["id"]) == str(local)), None)

    def _walk(self, parts: list[str]) -> str:
        """从根图往里走的节点号 → 最里面那一层的子图定义 id。"""
        scope: dict[str, Any] = self.graph
        layer = ""
        for depth, part in enumerate(parts):
            node = self._find(scope, part)
            kind = str((node or {}).get("type") or "")
            if node is None or kind not in self.defs:
                at = ":".join(parts[: depth + 1])
                raise _Bad(f"#{at} 不是子图节点", f"#{at} is not a subgraph node")
            layer, scope = kind, self.defs[kind]
        return layer

    def layer_arg(self, value: Any) -> str | None:
        """`graph`:缺省是根图;从根图往里走的节点号(字符串或列表)或者子图定义的 id。"""
        if value is None or value == "" or value == []:
            return None
        if isinstance(value, list) and value and all(isinstance(one, (str, int)) and _LOCAL.match(str(one)) for one in value):
            return self._walk([str(one) for one in value])
        if isinstance(value, str):
            text = value.strip().lstrip("#")
            if text in self.defs:
                return text
            if _PATH.match(text):
                return self._walk(text.split(":"))
        raise _Bad("「graph」要写子图节点的编号(如 \"12\"、\"12:5\")或者子图的 id",
                   "“graph” must be a subgraph node path (e.g. \"12\", \"12:5\") or a subgraph id")

    def node(self, ref: Any, graph: Any = None) -> tuple[str | None, str, dict[str, Any]]:
        """一个节点:(哪一层, 那一层里的编号或临时名字, 拷贝里的那个节点)。"""
        text = _str(ref, 400).lstrip("#")
        if _TEMP.match(text):
            if text not in self.temps:
                raise _Bad(f"「{text}」不在这一批里(临时名字要先在 add_node 里起,删掉的也指不到了)",
                           f"“{text}” is not in this batch (name it in an add_node first; removed nodes can't be used)")
            layer, raw = self.temps[text]
            return layer, text, raw
        if graph not in (None, "", []):
            layer = self.layer_arg(graph)
            if not _LOCAL.match(text):
                raise _Bad("给了「graph」时,节点写那一层里的编号", "With “graph”, give the node's id inside that layer")
            parts = [text]
        else:
            if not _PATH.match(text):
                raise _Bad("节点要写成画布摘要里的编号(12、子图里的 12:5)或者这一批里起的临时名字($a)",
                           "Refer to nodes as in the canvas summary (12, 12:5 inside a subgraph) or by a temporary name ($a)")
            parts = text.split(":")
            layer = self._walk(parts[:-1]) if len(parts) > 1 else None
        raw = self._find(self.scope(layer), parts[-1])
        if raw is None:
            raise _Bad(f"#{text} 不在画布上", f"#{text} is not on the canvas")
        return layer, parts[-1], raw

    def group(self, ref: Any, graph: Any = None) -> tuple[str | None, str, dict[str, Any]]:
        """摘要里的 ``gN``。引用绑定到读图时的对象,同一批先删前一个也不会让后面的编号漂移。"""
        text = _str(ref, 40).lower()
        if not _GROUP_REF.match(text):
            raise _Bad("分组要写成画布摘要里的 g1、g2", "Refer to a group as shown in the canvas summary: g1, g2")
        layer = self.layer_arg(graph)
        raw = self.group_refs.get((layer, text))
        if raw is None or raw not in canvas.groups_of(self.scope(layer)):
            raise _Bad(f"分组 {text} 不在这一层", f"Group {text} is not in this layer")
        return layer, text, raw

    def ref(self, layer: str | None, local: str) -> str:
        """给人看(也给「定位」用)的写法:子图里的按第一处用它的节点写;新节点是临时名字。"""
        if local.startswith("$") or layer is None:
            return local
        paths = self.paths.get(layer) or []
        return f"{paths[0]}:{local}" if paths else local

    def layer_info(self, layer: str | None) -> dict[str, Any] | None:
        if layer is None:
            return None
        if layer not in self.touched:
            self.touched.append(layer)
        return {"id": layer, "name": str(self.defs[layer].get("name") or layer)[:200], "uses": len(self.paths.get(layer) or [])}

    def _type_name(self, raw: dict[str, Any]) -> str:
        kind = str(raw.get("type") or "")
        return str(self.defs[kind].get("name") or kind)[:200] if kind in self.defs else kind

    def _instances(self, layer: str) -> list[tuple[str | None, dict[str, Any]]]:
        """用这份子图的节点(各层):(那个节点所在的层, 节点)。"""
        found: list[tuple[str | None, dict[str, Any]]] = []
        for owner in [None, *self.defs]:
            for raw in canvas.nodes_of(self.scope(owner)):
                if str(raw.get("type") or "") == layer:
                    found.append((owner, raw))
        return found

    # --- 节点有哪些口 -----------------------------------------------------------------------

    def outputs_of(self, raw: dict[str, Any]) -> list[tuple[str, str]]:
        listed = [(str(one.get("name") or one.get("type") or index), str(one.get("type") or "*"))
                  for index, one in enumerate(raw.get("outputs") or []) if isinstance(one, dict)]
        kind = str(raw.get("type") or "")
        if listed or kind in self.defs:
            return listed or [(str(one.get("name")), str(one.get("type") or "*"))
                              for one in self.defs[kind].get("outputs") or [] if isinstance(one, dict)]
        spec = self.info.get(kind) or {}
        types = spec.get("output") if isinstance(spec.get("output"), list) else []
        names = spec.get("output_name") if isinstance(spec.get("output_name"), list) else []
        return [(str(names[index] if index < len(names) and names[index] else ("COMBO" if isinstance(kind_, list) else kind_)),
                 "COMBO" if isinstance(kind_, list) else str(kind_)) for index, kind_ in enumerate(types)]

    def inputs_of(self, raw: dict[str, Any]) -> dict[str, tuple[str, bool]]:
        """名字 → (类型, 是不是一格控件)。节点定义里的全在(连成输入的控件也能接线),再加上节点上存着的(动态长出来的)。"""
        kind = str(raw.get("type") or "")
        found: dict[str, tuple[str, bool]] = {}
        if kind in self.defs:
            entries = {one.get("name"): one for one in raw.get("inputs") or [] if isinstance(one, dict)}
            for one in self.defs[kind].get("inputs") or []:
                if isinstance(one, dict) and one.get("name"):
                    entry = entries.get(one["name"])
                    found[str(one["name"])] = (str(one.get("type") or "*"), entry is None or "widget" in entry)
        elif isinstance(self.info.get(kind), dict):
            required, optional = diagnose._definitions(self.info[kind])  # noqa: SLF001 — 同一个插件
            for name, definition in {**optional, **required}.items():
                found[str(name)] = (diagnose._input_type(definition), not diagnose._is_socket(definition))  # noqa: SLF001
        for entry in raw.get("inputs") or []:
            if isinstance(entry, dict) and entry.get("name") and entry["name"] not in found:
                found[str(entry["name"])] = (str(entry.get("type") or "*"), "widget" in entry)
        return found

    def output_slot(self, raw: dict[str, Any], name: str, ref: str) -> tuple[int, str]:
        outputs = self.outputs_of(raw)
        exact = [index for index, (one, _) in enumerate(outputs) if one == name]
        typed = [index for index, (_, kind) in enumerate(outputs) if kind == name]
        picked = exact or (typed if len(typed) == 1 else [])
        if not picked:
            names = ", ".join(one for one, _ in outputs) or "-"
            raise _Bad(f"#{ref}({self._type_name(raw)})没有叫「{name}」的输出,有:{names}",
                       f"#{ref} ({self._type_name(raw)}) has no output “{name}”; it has: {names}")
        return picked[0], outputs[picked[0]][1]

    def input_entry(self, raw: dict[str, Any], name: str, ref: str) -> tuple[str, bool]:
        inputs = self.inputs_of(raw)
        if name not in inputs:
            names = ", ".join(inputs) or "-"
            raise _Bad(f"#{ref}({self._type_name(raw)})没有叫「{name}」的输入,有:{names}",
                       f"#{ref} ({self._type_name(raw)}) has no input “{name}”; it has: {names}")
        return inputs[name]

    # --- 连线(两种写法:根图的数组,子图里的对象) -------------------------------------------

    @staticmethod
    def _io_node(scope: dict[str, Any], key: str, default: int) -> str:
        return str((scope.get(key) or {}).get("id", default))

    def add_link(self, layer: str | None, origin: Any, origin_slot: int, target: Any, target_slot: int, kind: str) -> int:
        scope = self.scope(layer)
        links = scope.setdefault("links", [])
        link_id = self.link_seq
        self.link_seq += 1
        if layer is None and not any(isinstance(one, dict) for one in links):
            links.append([link_id, origin, origin_slot, target, target_slot, kind])
        else:
            links.append({"id": link_id, "origin_id": origin, "origin_slot": origin_slot, "target_id": target,
                          "target_slot": target_slot, "type": kind})
        return link_id

    def drop_link(self, layer: str | None, link_id: Any) -> None:
        """断一根线:线本身、两头节点上记着的、子图边界上记着的都去掉。"""
        scope = self.scope(layer)
        found = canvas._links(scope).get(str(link_id))  # noqa: SLF001 — 同一个插件
        scope["links"] = [one for one in scope.get("links") or [] if _link_id(one) != str(link_id)]
        if found is None:
            return
        origin, origin_slot, target, target_slot = str(found[0]), found[1], str(found[2]), found[3]
        definition = self.defs.get(layer or "")
        if definition is not None and origin == self._io_node(definition, "inputNode", canvas.SUBGRAPH_INPUT):
            declared = definition.get("inputs") or []
            if origin_slot < len(declared):
                declared[origin_slot]["linkIds"] = [one for one in declared[origin_slot].get("linkIds") or [] if str(one) != str(link_id)]
        else:
            source = self._find(scope, origin)
            outputs = (source or {}).get("outputs") or []
            if origin_slot < len(outputs) and isinstance(outputs[origin_slot], dict):
                outputs[origin_slot]["links"] = [one for one in outputs[origin_slot].get("links") or [] if str(one) != str(link_id)]
        if definition is not None and target == self._io_node(definition, "outputNode", canvas.SUBGRAPH_OUTPUT):
            declared = definition.get("outputs") or []
            if target_slot < len(declared):
                declared[target_slot]["linkIds"] = [one for one in declared[target_slot].get("linkIds") or [] if str(one) != str(link_id)]
            return
        for entry in (self._find(scope, target) or {}).get("inputs") or []:
            if isinstance(entry, dict) and str(entry.get("link")) == str(link_id):
                entry["link"] = None

    def links_of(self, layer: str | None, local: str) -> list[str]:
        return [key for key, link in canvas._links(self.scope(layer)).items()  # noqa: SLF001
                if str(link[0]) == str(local) or str(link[2]) == str(local)]

    # --- 控件的值 ---------------------------------------------------------------------------

    def widget_definition(self, raw: dict[str, Any], name: str, ref: str) -> Any:
        """一格控件的定义(节点定义里的那一项;子图节点上提升出来的,是里面那一格的)。不是控件就说清楚。"""
        kind = str(raw.get("type") or "")
        if kind in _NOTES:
            if name != "text":
                raise _Bad(f"笔记节点 #{ref} 只有「text」一格", f"Note #{ref} only has “text”")
            return ["STRING", {"multiline": True}]
        if kind in self.defs:
            promoted = self.promoted_names(raw)
            if name not in promoted:
                names = ", ".join(promoted) or "-"
                raise _Bad(f"子图节点 #{ref} 上没有提升出来的「{name}」,有:{names}(要改里面那一格就写 #{ref}:<编号>)",
                           f"Subgraph node #{ref} has no promoted “{name}”; it has: {names} (to change the inner widget use #{ref}:<id>)")
            return self.inner_definition(kind, name)
        spec = self.info.get(kind)
        if not isinstance(spec, dict):
            raise _Bad(f"这台 ComfyUI 没有节点类型「{kind}」,改不了 #{ref} 的控件", f"This ComfyUI has no node type “{kind}”; can't edit #{ref}")
        required, optional = diagnose._definitions(spec)  # noqa: SLF001
        definition = required.get(name, optional.get(name))
        if definition is None or diagnose._is_socket(definition):  # noqa: SLF001
            widgets = [one for one, _, _ in convert.widget_layout(raw, self.info) if one not in ("upload", "audioUI")]
            raise _Bad(f"#{ref}({kind})没有叫「{name}」的控件,有:{', '.join(widgets) or '-'}",
                       f"#{ref} ({kind}) has no widget “{name}”; it has: {', '.join(widgets) or '-'}")
        return definition

    def promoted_names(self, raw: dict[str, Any]) -> list[str]:
        """子图节点上提升出来的那几格(和 canvas._promoted / convert._from_subgraph_input 同一套认法)。"""
        definition = self.defs[str(raw.get("type"))]
        entries = {one.get("name"): one for one in raw.get("inputs") or [] if isinstance(one, dict) and one.get("name")}
        return [str(one.get("name")) for one in definition.get("inputs") or [] if isinstance(one, dict) and one.get("name")
                and (entries.get(one["name"]) is None or "widget" in entries[one["name"]])]

    def inner_definition(self, layer: str, name: str, depth: int = 0) -> Any:
        """子图输入口 `name` 接到里面哪一格控件:那一格的定义(再套一层子图就往里找)。找不到回 None(值就不按类型查)。"""
        definition = self.defs[layer]
        declared = [one for one in definition.get("inputs") or [] if isinstance(one, dict)]
        index = next((i for i, one in enumerate(declared) if one.get("name") == name), -1)
        source = self._io_node(definition, "inputNode", canvas.SUBGRAPH_INPUT)
        for key, link in canvas._links(definition).items():  # noqa: SLF001
            if str(link[0]) != source or link[1] != index:
                continue
            inner = self._find(definition, str(link[2]))
            entry = next((one for one in (inner or {}).get("inputs") or [] if isinstance(one, dict) and str(one.get("link")) == key),
                         None)
            if inner is None or entry is None:
                continue
            kind = str(inner.get("type") or "")
            if kind in self.defs and depth < 8:
                return self.inner_definition(kind, str(entry.get("name")), depth + 1)
            required, optional = diagnose._definitions(self.info.get(kind) or {})  # noqa: SLF001
            found = required.get(entry.get("name"), optional.get(entry.get("name")))
            if found is not None:
                return found
        return None

    def value(self, definition: Any, value: Any, name: str) -> Any:
        """一格的新值:类型对、在下拉里、在范围里。下拉的值换成列表里的写法(斜杠方向)。"""
        if isinstance(value, str) and len(value) > MAX_VALUE:
            raise _Bad(f"「{name}」的值太长了(上限 {MAX_VALUE} 字)", f"The value for “{name}” is too long (max {MAX_VALUE})")
        if not (isinstance(value, (str, bool)) or (isinstance(value, (int, float)) and value == value and abs(value) != float("inf"))):
            raise _Bad(f"「{name}」的值要是文字、数或者真假", f"The value for “{name}” must be text, a number or a boolean")
        if definition is None:
            return value
        kind = _type_of(definition)
        options = definition[1] if isinstance(definition, list) and len(definition) > 1 and isinstance(definition[1], dict) else {}
        if kind == diagnose.V3_COMBO:
            keys = [str(one.get("key")) for one in options.get("options") or [] if isinstance(one, dict) and one.get("key") is not None]
            if keys and value not in keys:
                raise _Bad(f"「{name}」= {value!r} 不在可选的值里:{', '.join(keys[:8])}", f"“{name}” = {value!r} is not one of: {', '.join(keys[:8])}")
            return value
        choices = _choices(definition)
        if choices is not None:
            if not isinstance(value, str):
                raise _Bad(f"「{name}」是下拉,要选列表里的一项", f"“{name}” is a dropdown; pick one of its values")
            exact = next((one for one in choices if one == value), None)
            normed = next((one for one in choices if isinstance(one, str) and one.replace("\\", "/") == value.replace("\\", "/")), None)
            picked = exact if exact is not None else normed
            if picked is None:
                close = [one for one in choices if isinstance(one, str) and value.lower().split("/")[-1] in one.lower()][:5] or choices[:5]
                raise _Bad(f"「{name}」= {value!r} 不在这台机器的下拉里(共 {len(choices)} 项),比如:{', '.join(map(str, close))}",
                           f"“{name}” = {value!r} is not available on this machine ({len(choices)} values), e.g. {', '.join(map(str, close))}")
            return picked
        if kind == "BOOLEAN":
            if not isinstance(value, bool):
                raise _Bad(f"「{name}」要 true / false", f"“{name}” must be true or false")
            return value
        if kind in ("INT", "FLOAT"):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise _Bad(f"「{name}」要一个数", f"“{name}” must be a number")
            if kind == "INT":
                if float(value) != int(value):
                    raise _Bad(f"「{name}」要整数", f"“{name}” must be an integer")
                value = int(value)
            low, high = options.get("min"), options.get("max")
            if (isinstance(low, (int, float)) and value < low) or (isinstance(high, (int, float)) and value > high):
                raise _Bad(f"「{name}」= {value} 超出了 {low} ~ {high}", f"“{name}” = {value} is outside {low} to {high}")
            return value
        if kind in ("STRING", "MARKDOWN", "TEXTAREA") and not isinstance(value, str):
            raise _Bad(f"「{name}」要一段文字", f"“{name}” must be text")
        return value

    def current(self, raw: dict[str, Any], name: str) -> Any:
        kind = str(raw.get("type") or "")
        stored = raw.get("widgets_values")
        if kind in _NOTES:
            return stored[0] if isinstance(stored, list) and stored else ""
        if kind in self.defs:
            promoted = self.promoted_names(raw)
            if isinstance(stored, dict):
                return stored.get(name)
            index = promoted.index(name) if name in promoted else -1
            return stored[index] if isinstance(stored, list) and 0 <= index < len(stored) else None
        return convert.widget_values(raw, self.info).get(name)

    def write(self, raw: dict[str, Any], name: str, value: Any) -> None:
        kind = str(raw.get("type") or "")
        stored = raw.get("widgets_values")
        if isinstance(stored, dict):
            stored[name] = value
            return
        if kind in _NOTES:
            raw["widgets_values"] = [value]
            return
        if kind in self.defs:
            index = self.promoted_names(raw).index(name)
        else:
            index = 0
            for one, _, extra in convert.widget_layout(raw, self.info):
                if one == name:
                    break
                index += 1 + extra
        values = list(stored) if isinstance(stored, list) else []
        values += [None] * (index + 1 - len(values))
        values[index] = value
        raw["widgets_values"] = values

    def linked(self, raw: dict[str, Any], name: str) -> bool:
        return any(isinstance(one, dict) and one.get("name") == name and one.get("link") is not None for one in raw.get("inputs") or [])

    # --- 一条一条 ---------------------------------------------------------------------------

    def run(self, ops: list[Any], locale: str) -> None:
        problems: list[tuple[str, str]] = []
        for index, op in enumerate(ops):
            name = str(op.get("op") or "") if isinstance(op, dict) else ""
            try:
                if not isinstance(op, dict) or name not in OPS:
                    raise _Bad(f"不认识的改动「{name}」,能用的:{', '.join(OPS)}", f"Unknown op “{name}”; use one of: {', '.join(OPS)}")
                if self.structural:
                    raise _Bad("打包 / 拆开子图要放在这一批的最后(后面的改动指不到打包以后的节点),分两批来",
                               "to_subgraph / unpack_subgraph must be the last op of a batch; send the rest as another batch")
                getattr(self, f"op_{name}")(op)
            except _Bad as bad:
                problems.append((f"第 {index + 1} 条({name or '?'}):{bad.zh}", f"Op {index + 1} ({name or '?'}): {bad.en}"))
                if len(problems) >= MAX_PROBLEMS:
                    break
        if problems:
            raise ComfyError(say(locale, "这一批改动一条都没改(要么全成,要么一样不改):\n" + "\n".join(zh for zh, _ in problems),
                                 "Nothing was changed (a batch applies entirely or not at all):\n" + "\n".join(en for _, en in problems)))

    def _record(self, bridge: dict[str, Any], change: dict[str, Any], layer: str | None) -> None:
        self.bridge.append({**bridge, "layer": layer})
        info = self.layer_info(layer)
        self.changes.append({**change, **({"layer": info} if info else {})})

    def op_add_node(self, op: dict[str, Any]) -> None:
        temp = _str(op.get("id"), 40)
        if not _TEMP.match(temp):
            raise _Bad("add_node 要一个临时名字「id」,写成 $a 这样", "add_node needs a temporary “id” like $a")
        if temp in self.temps:
            raise _Bad(f"临时名字「{temp}」用过了", f"The temporary name “{temp}” is already used")
        kind = _str(op.get("type"), 200)
        layer = self.layer_arg(op.get("graph"))
        if kind in self.defs:
            raise _Bad("这一版不能加子图节点(可以把节点打包成子图:to_subgraph)", "Adding subgraph nodes isn't supported; use to_subgraph")
        spec = self.info.get(kind)
        if kind not in _NOTES and not isinstance(spec, dict):
            raise _Bad(f"这台 ComfyUI 没有节点类型「{kind}」(comfy_node_types 查准名字;缺的节点包先装)",
                       f"This ComfyUI has no node type “{kind}” (look it up with comfy_node_types; install missing packs first)")
        near = None
        if op.get("near") not in (None, ""):
            near_layer, near_local, _ = self.node(op.get("near"))
            if near_layer != layer:
                raise _Bad("「near」要和新节点在同一层", "“near” must be in the same layer as the new node")
            near = near_local
        title = _str(op.get("title"))
        raw = self.new_node(kind, spec)
        widgets = op.get("widgets") if isinstance(op.get("widgets"), dict) else {}
        if op.get("widgets") is not None and not isinstance(op.get("widgets"), dict):
            raise _Bad("「widgets」要写成 {控件名: 值}", "“widgets” must be an object {widget: value}")
        values: dict[str, Any] = {}
        for name, given in widgets.items():
            values[str(name)] = self.value(self.widget_definition(raw, str(name), temp), given, str(name))
            self.write(raw, str(name), values[str(name)])
        if title:
            raw["title"] = title
        self.scope(layer).setdefault("nodes", []).append(raw)
        self.temps[temp] = (layer, raw)
        bridge = {"op": "add_node", "id": temp, "type": kind, "widgets": values, **({"title": title} if title else {}),
                  **({"near": near} if near else {})}
        change = {"op": "add_node", "node": temp, "type": kind, "widgets": values, **({"title": title} if title else {}),
                  **({"near": self.ref(layer, near)} if near else {})}
        self._record(bridge, change, layer)

    def new_node(self, kind: str, spec: dict[str, Any] | None) -> dict[str, Any]:
        """一个新节点在界面格式里的样子:插口照节点定义排(可选的标成 shape 7),控件的值照缺省值,输出照定义。"""
        raw: dict[str, Any] = {"id": self.node_seq, "type": kind, "pos": [0, 0], "size": [300, 120], "flags": {}, "order": 0,
                               "mode": 0, "inputs": [], "outputs": [], "properties": {"Node name for S&R": kind}}
        self.node_seq += 1
        if kind in _NOTES:
            raw["widgets_values"] = [""]
            return raw
        required, optional = diagnose._definitions(spec or {})  # noqa: SLF001
        for section, defs in (("required", required), ("optional", optional)):
            for name, definition in defs.items():
                if diagnose._is_socket(definition):  # noqa: SLF001
                    entry: dict[str, Any] = {"name": name, "type": diagnose._input_type(definition), "link": None}  # noqa: SLF001
                    if section == "optional":
                        entry["shape"] = 7
                    raw["inputs"].append(entry)
        raw["outputs"] = [{"name": name, "type": kind_, "links": []} for name, kind_ in self.outputs_of(raw)]
        values: list[Any] = []
        for name, definition, extra in convert.widget_layout(raw, self.info):
            present, default = convert.widget_default(definition)
            values.append(default if present else ("image" if name == "upload" else None))
            values += ["randomize"] * extra
        raw["widgets_values"] = values
        return raw

    def op_remove_node(self, op: dict[str, Any]) -> None:
        layer, local, raw = self.node(op.get("node"), op.get("graph"))
        cut = self.links_of(layer, str(raw["id"]))
        for link in cut:
            self.drop_link(layer, link)
        scope = self.scope(layer)
        scope["nodes"] = [one for one in scope.get("nodes") or [] if one is not raw]
        self.temps.pop(local, None)
        change = {"op": "remove_node", "node": self.ref(layer, local), "type": self._type_name(raw),
                  **({"title": str(raw["title"])[:200]} if raw.get("title") else {}), "links": len(cut)}
        self._record({"op": "remove_node", "node": local}, change, layer)

    @staticmethod
    def _end(text: Any) -> tuple[str, str]:
        """`12.model` / `$a.MODEL` / `@in.prompt` → (节点或 @in / @out, 口的名字)。"""
        value = _str(text, 400)
        head, dot, name = value.partition(".")
        if not dot or not name:
            raise _Bad(f"「{value}」要写成 节点.口的名字(如 4.MODEL、$a.model、@in.prompt)",
                       f"“{value}” must look like node.slot (e.g. 4.MODEL, $a.model, @in.prompt)")
        return head.lstrip("#"), name

    def _side(self, head: str, graph: Any, other: str | None) -> tuple[str | None, str, dict[str, Any] | None]:
        if head in ("@in", "@out"):
            layer = self.layer_arg(graph) if graph not in (None, "", []) else other
            if layer is None:
                raise _Bad(f"{head} 只在子图里有(连线另一头要是子图里的节点,或者给「graph」)",
                           f"{head} only exists inside a subgraph (the other end must be inside one, or give “graph”)")
            return layer, head, None
        return self.node(head, graph)

    def op_connect(self, op: dict[str, Any]) -> None:
        source_head, output = self._end(op.get("from"))
        target_head, input_name = self._end(op.get("to"))
        if source_head == "@out" or target_head == "@in":
            raise _Bad("@in 只能当起点、@out 只能当终点", "@in can only be a source and @out only a target")
        graph = op.get("graph")
        ends = {}
        for key, head in (("from", source_head), ("to", target_head)):
            if head not in ("@in", "@out"):
                ends[key] = self.node(head, graph)
        known = [layer for layer, _, _ in ends.values()]
        source = ends.get("from") or self._side(source_head, graph, known[0] if known else None)
        target = ends.get("to") or self._side(target_head, graph, known[0] if known else None)
        layer = source[0]
        if source[0] != target[0]:
            raise _Bad("连线不能跨层:子图里外之间走子图的 @in / @out 口", "Links can't cross layers; use the subgraph's @in / @out")
        definition = self.defs.get(layer or "")
        if source[1] == "@in":
            declared = [one for one in definition.get("inputs") or [] if isinstance(one, dict)]
            slot = next((i for i, one in enumerate(declared) if one.get("name") == output), -1)
            if slot < 0:
                raise _Bad(f"子图「{definition.get('name')}」没有叫「{output}」的输入口", f"Subgraph “{definition.get('name')}” has no input “{output}”")
            out_type, origin = str(declared[slot].get("type") or "*"), self._io_node(definition, "inputNode", canvas.SUBGRAPH_INPUT)
            source_ref = "@in"
        else:
            slot, out_type = self.output_slot(source[2], output, self.ref(layer, source[1]))
            origin, source_ref = source[2]["id"], self.ref(layer, source[1])
        if target[1] == "@out":
            declared = [one for one in definition.get("outputs") or [] if isinstance(one, dict)]
            target_slot = next((i for i, one in enumerate(declared) if one.get("name") == input_name), -1)
            if target_slot < 0:
                raise _Bad(f"子图「{definition.get('name')}」没有叫「{input_name}」的输出口",
                           f"Subgraph “{definition.get('name')}” has no output “{input_name}”")
            in_type = str(declared[target_slot].get("type") or "*")
            replaced = [str(one) for one in declared[target_slot].get("linkIds") or []]
            target_ref = "@out"
        else:
            target_ref = self.ref(layer, target[1])
            in_type, _ = self.input_entry(target[2], input_name, target_ref)
            entries = [one for one in target[2].get("inputs") or [] if isinstance(one, dict)]
            entry = next((one for one in entries if one.get("name") == input_name), None)
            replaced = [str(entry["link"])] if entry is not None and entry.get("link") is not None else []
        if not convert.connectable(out_type, in_type):
            raise _Bad(f"{source_ref}.{output} 出来的是 {out_type},{target_ref}.{input_name} 要 {in_type},接不上",
                       f"{source_ref}.{output} gives {out_type} but {target_ref}.{input_name} takes {in_type}")
        before = self._describe_link(layer, replaced[0]) if replaced else None
        for one in replaced:
            self.drop_link(layer, one)
        if target[1] == "@out":
            target_id = self._io_node(definition, "outputNode", canvas.SUBGRAPH_OUTPUT)
        else:
            entries = target[2].setdefault("inputs", [])
            entry = next((one for one in entries if isinstance(one, dict) and one.get("name") == input_name), None)
            if entry is None:
                entry = {"name": input_name, "type": in_type, "widget": {"name": input_name}, "link": None}
                entries.append(entry)
            target_slot, target_id = entries.index(entry), target[2]["id"]
        link = self.add_link(layer, _as_id(origin), slot, _as_id(target_id), target_slot, out_type)
        if target[1] == "@out":
            definition["outputs"][target_slot]["linkIds"] = [link]
        else:
            entry["link"] = link
        if source[1] == "@in":
            definition["inputs"][slot].setdefault("linkIds", []).append(link)
        else:
            outputs = source[2].setdefault("outputs", [])
            if slot < len(outputs) and isinstance(outputs[slot], dict):
                outputs[slot].setdefault("links", []).append(link)
        bridge = {"op": "connect", "from": {"node": source[1], "name": output}, "to": {"node": target[1], "name": input_name}}
        change = {"op": "connect", "from": {"node": source_ref, "output": output, "type": out_type},
                  "to": {"node": target_ref, "input": input_name}, **({"replaces": before} if before else {})}
        self._record(bridge, change, layer)

    def _describe_link(self, layer: str | None, link_id: str) -> dict[str, Any] | None:
        found = canvas._links(self.scope(layer)).get(str(link_id))  # noqa: SLF001
        if found is None:
            return None
        definition = self.defs.get(layer or "")
        if definition is not None and str(found[0]) == self._io_node(definition, "inputNode", canvas.SUBGRAPH_INPUT):
            declared = definition.get("inputs") or []
            return {"node": "@in", "output": str(declared[found[1]].get("name")) if found[1] < len(declared) else ""}
        source = self._find(self.scope(layer), str(found[0]))
        local = str(found[0])
        outputs = self.outputs_of(source) if source else []
        return {"node": self.ref(layer, self._temp_or(local, source)),
                "output": outputs[found[1]][0] if found[1] < len(outputs) else str(found[1])}

    def _temp_or(self, local: str, raw: dict[str, Any] | None) -> str:
        return next((name for name, (_, one) in self.temps.items() if one is raw), local)

    def op_disconnect(self, op: dict[str, Any]) -> None:
        head, name = self._end(op.get("to"))
        graph = op.get("graph")
        if head == "@out":
            layer = self.layer_arg(graph)
            definition = self.defs.get(layer or "")
            if definition is None:
                raise _Bad("@out 只在子图里有,给「graph」", "@out only exists inside a subgraph; give “graph”")
            declared = [one for one in definition.get("outputs") or [] if isinstance(one, dict)]
            slot = next((i for i, one in enumerate(declared) if one.get("name") == name), -1)
            if slot < 0 or not declared[slot].get("linkIds"):
                raise _Bad(f"子图的输出口「{name}」没连着", f"The subgraph output “{name}” isn't connected")
            link, target = str(declared[slot]["linkIds"][0]), "@out"
            target_ref = "@out"
        else:
            layer, target, raw = self.node(head, graph)
            target_ref = self.ref(layer, target)
            self.input_entry(raw, name, target_ref)
            entry = next((one for one in raw.get("inputs") or [] if isinstance(one, dict) and one.get("name") == name), None)
            if entry is None or entry.get("link") is None:
                raise _Bad(f"#{target_ref} 的「{name}」本来就没连", f"#{target_ref}.{name} isn't connected")
            link = str(entry["link"])
        before = self._describe_link(layer, link)
        self.drop_link(layer, link)
        change = {"op": "disconnect", "to": {"node": target_ref, "input": name}, **({"from": before} if before else {})}
        self._record({"op": "disconnect", "to": {"node": target, "name": name}}, change, layer)

    def op_set_widget(self, op: dict[str, Any]) -> None:
        layer, local, raw = self.node(op.get("node"), op.get("graph"))
        name = _str(op.get("widget"))
        ref = self.ref(layer, local)
        definition = self.widget_definition(raw, name, ref)
        if self.linked(raw, name):
            raise _Bad(f"#{ref} 的「{name}」连着线,值由上游给(要改值先 disconnect)",
                       f"#{ref}.{name} is wired; its value comes from upstream (disconnect it first)")
        if "value" not in op:
            raise _Bad("set_widget 要「value」", "set_widget needs “value”")
        value = self.value(definition, op.get("value"), name)
        before = self.current(raw, name)
        self.write(raw, name, value)
        change = {"op": "set_widget", "node": ref, "type": self._type_name(raw), "widget": name, "before": _shown(before),
                  "after": _shown(value)}
        self._record({"op": "set_widget", "node": local, "widget": name, "value": value}, change, layer)

    def op_set_title(self, op: dict[str, Any]) -> None:
        layer, local, raw = self.node(op.get("node"), op.get("graph"))
        title = _str(op.get("title"))
        if not title:
            raise _Bad("set_title 要一个「title」", "set_title needs a “title”")
        before = str(raw.get("title") or "")
        raw["title"] = title
        change = {"op": "set_title", "node": self.ref(layer, local), "type": self._type_name(raw), "before": before, "after": title}
        self._record({"op": "set_title", "node": local, "title": title}, change, layer)

    def op_set_position(self, op: dict[str, Any]) -> None:
        """Move any node in its own layer. Layout is graph data, so it follows the same atomic/undoable edit path as values and links."""
        layer, local, raw = self.node(op.get("node"), op.get("graph"))
        values = (op.get("x"), op.get("y"))
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in values):
            raise _Bad("set_position 的 x / y 要有限数字", "set_position x / y must be finite numbers")
        if any(abs(float(value)) > MAX_COORDINATE for value in values):
            raise _Bad(f"set_position 的 x / y 不能超过 ±{MAX_COORDINATE}",
                       f"set_position x / y must stay within ±{MAX_COORDINATE}")
        before_raw = raw.get("pos")
        before = list(before_raw[:2]) if isinstance(before_raw, (list, tuple)) and len(before_raw) >= 2 else [0, 0]
        after = [float(values[0]), float(values[1])]
        raw["pos"] = after
        change = {"op": "set_position", "node": self.ref(layer, local), "type": self._type_name(raw),
                  "before": before, "after": after}
        self._record({"op": "set_position", "node": local, "x": after[0], "y": after[1]}, change, layer)

    # --- 空间分组 ---------------------------------------------------------------------------

    @staticmethod
    def _coordinate(value: Any, name: str, *, positive: bool = False) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise _Bad(f"分组的 {name} 要有限数字", f"Group {name} must be a finite number")
        number = float(value)
        if abs(number) > MAX_COORDINATE or (positive and number <= 0):
            rule = f"大于 0 且不超过 {MAX_COORDINATE}" if positive else f"不能超过 ±{MAX_COORDINATE}"
            en = f"greater than 0 and at most {MAX_COORDINATE}" if positive else f"within ±{MAX_COORDINATE}"
            raise _Bad(f"分组的 {name} 要{rule}", f"Group {name} must be {en}")
        return number

    @staticmethod
    def _group_bounds(raw: dict[str, Any]) -> list[float]:
        bounding = raw.get("bounding")
        if isinstance(bounding, (list, tuple)) and len(bounding) >= 4:
            return [float(value) for value in bounding[:4]]
        pos, size = raw.get("pos"), raw.get("size")
        if isinstance(pos, (list, tuple)) and len(pos) >= 2 and isinstance(size, (list, tuple)) and len(size) >= 2:
            return [float(pos[0]), float(pos[1]), float(size[0]), float(size[1])]
        return [0.0, 0.0, 400.0, 300.0]

    @staticmethod
    def _group_title(value: Any) -> str:
        title = _str(value)
        if not title or any(ord(char) < 32 for char in title):
            raise _Bad("分组要有标题(不超过 200 字)", "A group needs a title (at most 200 characters)")
        return title

    @staticmethod
    def _group_color(value: Any) -> str:
        color = _str(value, 20)
        if not _COLOR.match(color):
            raise _Bad("分组颜色要写成 #RGB 或 #RRGGBB", "Group color must be #RGB or #RRGGBB")
        return color

    def op_add_group(self, op: dict[str, Any]) -> None:
        layer = self.layer_arg(op.get("graph"))
        title = self._group_title(op.get("title"))
        bounds = [self._coordinate(op.get("x"), "x"), self._coordinate(op.get("y"), "y"),
                  self._coordinate(op.get("width"), "width", positive=True),
                  self._coordinate(op.get("height"), "height", positive=True)]
        color = self._group_color(op.get("color", "#3f789e"))
        raw = {"id": self.group_seq, "title": title, "bounding": bounds, "color": color, "flags": {}}
        self.group_seq += 1
        self.scope(layer).setdefault("groups", []).append(raw)
        payload = {"op": "add_group", "title": title, "x": bounds[0], "y": bounds[1], "width": bounds[2], "height": bounds[3],
                   "color": color}
        self._record(payload, {**payload, "bounds": bounds}, layer)

    def op_set_group(self, op: dict[str, Any]) -> None:
        layer, ref, raw = self.group(op.get("group"), op.get("graph"))
        fields = ("title", "x", "y", "width", "height", "color")
        if not any(field in op for field in fields):
            raise _Bad("set_group 至少要改标题、位置、大小或颜色中的一项",
                       "set_group must change at least one of title, position, size or color")
        before_bounds = self._group_bounds(raw)
        bounds = list(before_bounds)
        for index, name in enumerate(("x", "y", "width", "height")):
            if name in op:
                bounds[index] = self._coordinate(op[name], name, positive=name in ("width", "height"))
        before_title = str(raw.get("title") or "Group")
        title = self._group_title(op["title"]) if "title" in op else before_title
        before_color = str(raw.get("color") or "#3f789e")
        color = self._group_color(op["color"]) if "color" in op else before_color
        raw.update(title=title, bounding=bounds, color=color)
        payload = {"op": "set_group", "group": ref, "title": title, "x": bounds[0], "y": bounds[1], "width": bounds[2],
                   "height": bounds[3], "color": color}
        change = {**payload, "before": {"title": before_title, "bounds": before_bounds, "color": before_color},
                  "after": {"title": title, "bounds": bounds, "color": color}}
        self._record(payload, change, layer)

    def op_remove_group(self, op: dict[str, Any]) -> None:
        layer, ref, raw = self.group(op.get("group"), op.get("graph"))
        self.scope(layer)["groups"] = [one for one in canvas.groups_of(self.scope(layer)) if one is not raw]
        change = {"op": "remove_group", "group": ref, "title": str(raw.get("title") or "Group"),
                  "bounds": self._group_bounds(raw)}
        self._record({"op": "remove_group", "group": ref}, change, layer)

    def _mode(self, op: dict[str, Any], what: str) -> None:
        layer, local, raw = self.node(op.get("node"), op.get("graph"))
        on = op.get("on", True)
        if not isinstance(on, bool):
            raise _Bad("「on」要 true / false", "“on” must be true or false")
        mode = _MODES[what] if on else 0
        before = raw.get("mode") if isinstance(raw.get("mode"), int) else 0
        raw["mode"] = mode
        change = {"op": what, "node": self.ref(layer, local), "type": self._type_name(raw), "on": on,
                  "before": _MODE_NAMES.get(before, str(before))}
        self._record({"op": "mode", "node": local, "mode": mode}, change, layer)

    def op_bypass(self, op: dict[str, Any]) -> None:
        self._mode(op, "bypass")

    def op_mute(self, op: dict[str, Any]) -> None:
        self._mode(op, "mute")

    # --- 子图的边界 -------------------------------------------------------------------------

    def _subgraph_layer(self, op: dict[str, Any]) -> str:
        layer = self.layer_arg(op.get("graph"))
        if layer is None:
            raise _Bad("要给「graph」:哪一份子图", "Give “graph”: which subgraph")
        return layer

    def _io_name(self, op: dict[str, Any]) -> str:
        name = _str(op.get("name"), 100)
        if not _NAME.match(name):
            raise _Bad("口要有名字(不超过 100 字)", "The slot needs a name (at most 100 characters)")
        return name

    def add_io(self, layer: str, side: str, name: str, kind: str, widget: bool = False) -> None:
        definition = self.defs[layer]
        definition.setdefault(side, []).append({"id": str(uuid.uuid4()), "name": name, "type": kind, "linkIds": []})
        for _, raw in self._instances(layer):
            if side == "inputs":
                raw.setdefault("inputs", []).append({"name": name, "type": kind, "link": None,
                                                     **({"widget": {"name": name}} if widget else {})})
            else:
                raw.setdefault("outputs", []).append({"name": name, "type": kind, "links": []})

    def _add_io(self, op: dict[str, Any], side: str) -> None:
        layer = self._subgraph_layer(op)
        name = self._io_name(op)
        kind = _str(op.get("type"), 100) or "*"
        if not _NAME.match(kind):
            raise _Bad("「type」要写类型名(MODEL、IMAGE、INT……)", "“type” must be a type name (MODEL, IMAGE, INT, …)")
        if any(isinstance(one, dict) and one.get("name") == name for one in self.defs[layer].get(side) or []):
            raise _Bad(f"子图已经有叫「{name}」的{'输入' if side == 'inputs' else '输出'}口",
                       f"The subgraph already has an {'input' if side == 'inputs' else 'output'} named “{name}”")
        self.add_io(layer, side, name, kind)
        what = "add_subgraph_input" if side == "inputs" else "add_subgraph_output"
        self._record({"op": "add_io", "side": side[:-1], "name": name, "type": kind},
                     {"op": what, "name": name, "type": kind}, layer)

    def op_add_subgraph_input(self, op: dict[str, Any]) -> None:
        self._add_io(op, "inputs")

    def op_add_subgraph_output(self, op: dict[str, Any]) -> None:
        self._add_io(op, "outputs")

    def remove_io(self, layer: str, side: str, index: int) -> int:
        """删掉边界上第 `index` 个口:里面接着它的线、外面用它的节点上的那一格(和接着的线、提升出来的值)。回断了几根线。"""
        definition = self.defs[layer]
        declared = definition[side]
        name = declared[index].get("name")
        cut = 0
        inward = side == "inputs"
        io = self._io_node(definition, "inputNode" if inward else "outputNode",
                           canvas.SUBGRAPH_INPUT if inward else canvas.SUBGRAPH_OUTPUT)
        for key, link in list(canvas._links(definition).items()):  # noqa: SLF001
            end, slot = (link[0], link[1]) if inward else (link[2], link[3])
            if str(end) == io and slot == index:
                self.drop_link(layer, key)
                cut += 1
        self._shift(definition, io, "origin" if inward else "target", index)
        for owner, raw in self._instances(layer):
            entries = raw.get("inputs" if inward else "outputs") or []
            position = next((i for i, one in enumerate(entries) if isinstance(one, dict) and one.get("name") == name), -1)
            if inward:
                promoted = self.promoted_names(raw)
                stored = raw.get("widgets_values")
                if name in promoted and isinstance(stored, list) and promoted.index(name) < len(stored):
                    stored.pop(promoted.index(name))
                elif isinstance(stored, dict):
                    stored.pop(name, None)
            if position < 0:
                continue
            links = [entries[position]["link"]] if inward and entries[position].get("link") is not None else \
                [] if inward else list(entries[position].get("links") or [])
            for link in links:
                self.drop_link(owner, link)
                cut += 1
            self._shift(self.scope(owner), raw["id"], "target" if inward else "origin", position)
            entries.pop(position)
        declared.pop(index)
        return cut

    @staticmethod
    def _shift(scope: dict[str, Any], node_id: Any, end: str, position: int) -> None:
        """一个节点删掉第 `position` 个口以后,接着它后面那几个口的线的槽位号减一。"""
        for link in scope.get("links") or []:
            if isinstance(link, dict):
                if str(link.get(f"{end}_id")) == str(node_id) and isinstance(link.get(f"{end}_slot"), int) and link[f"{end}_slot"] > position:
                    link[f"{end}_slot"] -= 1
            elif isinstance(link, list) and len(link) >= 5:
                node_at, slot_at = (1, 2) if end == "origin" else (3, 4)
                if str(link[node_at]) == str(node_id) and isinstance(link[slot_at], int) and link[slot_at] > position:
                    link[slot_at] -= 1

    def op_remove_subgraph_io(self, op: dict[str, Any]) -> None:
        layer = self._subgraph_layer(op)
        name = self._io_name(op)
        side = op.get("side")
        definition = self.defs[layer]
        found = [(key, i) for key in ("inputs", "outputs") for i, one in enumerate(definition.get(key) or [])
                 if isinstance(one, dict) and one.get("name") == name and (side in (None, "") or key == f"{side}s")]
        if side not in (None, "", "input", "output"):
            raise _Bad("「side」写 input 或 output", "“side” must be input or output")
        if not found:
            raise _Bad(f"子图「{definition.get('name')}」没有叫「{name}」的口", f"Subgraph “{definition.get('name')}” has no slot “{name}”")
        if len(found) > 1:
            raise _Bad(f"输入、输出都有叫「{name}」的口,给「side」", f"Both an input and an output are named “{name}”; give “side”")
        key, index = found[0]
        cut = self.remove_io(layer, key, index)
        self._record({"op": "remove_io", "side": key[:-1], "name": name},
                     {"op": "remove_subgraph_io", "side": key[:-1], "name": name, "links": cut}, layer)

    def op_promote_widget(self, op: dict[str, Any]) -> None:
        layer, local, raw = self.node(op.get("node"), op.get("graph"))
        if layer is None:
            raise _Bad("提升控件指的是子图里面的节点(12:5 这样写)", "promote_widget is for a node inside a subgraph (like 12:5)")
        ref = self.ref(layer, local)
        name = _str(op.get("widget"))
        definition = self.widget_definition(raw, name, ref)
        if self.linked(raw, name):
            raise _Bad(f"#{ref} 的「{name}」已经连着线了", f"#{ref}.{name} is already wired")
        taken = [str(one.get("name")) for one in self.defs[layer].get("inputs") or [] if isinstance(one, dict)]
        unique = name if name not in taken else next(f"{name}_{n}" for n in range(1, 1000) if f"{name}_{n}" not in taken)
        kind = "COMBO" if _choices(definition) is not None else _type_of(definition)
        current = self.current(raw, name)
        self.add_io(layer, "inputs", unique, kind, widget=True)
        for _, instance in self._instances(layer):
            stored = instance.get("widgets_values")
            if isinstance(stored, dict):
                stored[unique] = current
            else:
                values = list(stored) if isinstance(stored, list) else []
                at = self.promoted_names(instance).index(unique)
                values += [None] * (at - len(values))
                values.insert(at, current)
                instance["widgets_values"] = values
        definition_layer = self.defs[layer]
        slot = len(definition_layer["inputs"]) - 1
        entries = raw.setdefault("inputs", [])
        entry = next((one for one in entries if isinstance(one, dict) and one.get("name") == name), None)
        if entry is None:
            entry = {"name": name, "type": kind, "widget": {"name": name}, "link": None}
            entries.append(entry)
        link = self.add_link(layer, _as_id(self._io_node(definition_layer, "inputNode", canvas.SUBGRAPH_INPUT)), slot,
                             raw["id"], entries.index(entry), kind)
        entry["link"] = link
        definition_layer["inputs"][slot]["linkIds"] = [link]
        change = {"op": "promote_widget", "node": ref, "type": self._type_name(raw), "widget": name, "name": unique,
                  "value": _shown(current)}
        self._record({"op": "promote", "node": local, "widget": name, "name": unique}, change, layer)

    def op_unpromote_widget(self, op: dict[str, Any]) -> None:
        layer, local, raw = self.node(op.get("node"), op.get("graph"))
        if layer is None:
            raise _Bad("收回控件指的是子图里面的节点(12:5 这样写)", "unpromote_widget is for a node inside a subgraph (like 12:5)")
        ref = self.ref(layer, local)
        name = _str(op.get("widget"))
        definition = self.defs[layer]
        entry = next((one for one in raw.get("inputs") or [] if isinstance(one, dict) and one.get("name") == name), None)
        link = canvas._links(definition).get(str((entry or {}).get("link")))  # noqa: SLF001
        source = self._io_node(definition, "inputNode", canvas.SUBGRAPH_INPUT)
        if entry is None or link is None or str(link[0]) != source:
            raise _Bad(f"#{ref} 的「{name}」没有提升出去", f"#{ref}.{name} isn't promoted")
        declared = definition.get("inputs") or []
        index = link[1]
        shared = len(declared[index].get("linkIds") or []) > 1 if index < len(declared) else False
        io_name = str(declared[index].get("name")) if index < len(declared) else name
        if shared:
            self.drop_link(layer, entry["link"])
        else:
            self.remove_io(layer, "inputs", index)
        change = {"op": "unpromote_widget", "node": ref, "type": self._type_name(raw), "widget": name, "name": io_name}
        self._record({"op": "unpromote", "node": local, "widget": name}, change, layer)

    # --- 只改结构的两种 ---------------------------------------------------------------------

    def op_to_subgraph(self, op: dict[str, Any]) -> None:
        refs = op.get("nodes")
        if not isinstance(refs, list) or not refs or len(refs) > 500:
            raise _Bad("to_subgraph 要「nodes」:同一层里的几个节点", "to_subgraph needs “nodes”: nodes in the same layer")
        found = [self.node(one, op.get("graph")) for one in refs]
        layers = {layer for layer, _, _ in found}
        if len(layers) != 1:
            raise _Bad("要打包的节点得在同一层", "The nodes to pack must be in the same layer")
        layer = found[0][0]
        locals_ = [local for _, local, _ in found]
        if len(set(locals_)) != len(locals_):
            raise _Bad("同一个节点写了两遍", "A node is listed twice")
        name = _str(op.get("name"), 100)
        self.structural = True
        change = {"op": "to_subgraph", "nodes": [{"node": self.ref(layer, local), "type": self._type_name(raw)} for _, local, raw in found],
                  **({"name": name} if name else {})}
        self._record({"op": "to_subgraph", "nodes": locals_, **({"name": name} if name else {})}, change, layer)

    def op_unpack_subgraph(self, op: dict[str, Any]) -> None:
        layer, local, raw = self.node(op.get("node"), op.get("graph"))
        kind = str(raw.get("type") or "")
        if kind not in self.defs:
            raise _Bad(f"#{self.ref(layer, local)} 不是子图节点", f"#{self.ref(layer, local)} is not a subgraph node")
        self.structural = True
        change = {"op": "unpack_subgraph", "node": self.ref(layer, local), "name": self._type_name(raw),
                  "uses": len(self.paths.get(kind) or [])}
        self._record({"op": "unpack", "node": local}, change, layer)


def _as_id(value: Any) -> Any:
    """节点号照原样存(多是数);边界那两个虚拟节点是负数。"""
    text = str(value)
    return int(text) if _LOCAL.match(text) else value


def _shown(value: Any) -> Any:
    """清单上显示的值:长文字截短。"""
    if isinstance(value, str) and len(value) > 300:
        return value[:300] + "…"
    return value


def plan(content: dict[str, Any], ops: list[Any], object_info: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """一批改动的计划(见模块说明)。说不通就整批不交(ComfyError,每条说不通的都列出来)。"""
    planner = _Planner(content, object_info)
    planner.run(ops, locale)
    before = diagnose.check(content, object_info, comfy, locale)
    after = diagnose.check(planner.graph, object_info, comfy, locale)
    fixed, introduced = diagnose.compare(before["findings"], after["findings"])
    return {
        "ops": planner.bridge,
        "changes": planner.changes,
        "subgraphs": [{"id": layer, "name": str(planner.defs[layer].get("name") or layer)[:200],
                       "uses": len(planner.paths.get(layer) or [])} for layer in planner.touched],
        "structural": planner.structural,
        "check": {"before": before["counts"], "after": after["counts"], "fixed": fixed, "introduced": introduced,
                  "baseline": [{key: one[key] for key in _BASELINE_KEYS if key in one} for one in before["findings"]]},
    }


def edit_plan(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """`{"op": "edit_plan", "content", "ops"}`。只问图里和要加的那几类节点的定义。"""
    content = live_graph(payload, locale)
    ops = payload.get("ops")
    if not isinstance(ops, list) or not ops:
        raise ComfyError(say(locale, "「ops」要是一组改动", "“ops” must be a list of changes"))
    if len(ops) > MAX_OPS:
        raise ComfyError(say(locale, f"一批最多 {MAX_OPS} 条改动,分几批来", f"At most {MAX_OPS} ops per batch; split it"))
    wanted = canvas.class_types(content) | {str(op.get("type")) for op in ops
                                             if isinstance(op, dict) and op.get("op") == "add_node" and isinstance(op.get("type"), str)}
    object_info = node_catalog.classes(comfy, wanted)
    return plan(content, ops, object_info, comfy, locale)


__all__ = ["MAX_OPS", "OPS", "STRUCTURAL", "edit_plan", "plan"]
