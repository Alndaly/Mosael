"""应用表单(ADR 0038 §2):作者从一张工作流**全部能填的项**(graph.items)里挑出几项、起名、排序、收窄可选值,存进
**这张工作流的 JSON** —— 和别的 ComfyUI 扩展同一个做法(ComfyUI 前端照原样存回节点 `properties` 和图上的 `extra`):

- 节点上:`properties.mosael = {"expose": {<输入名>: {"label", "order", "main"?, "choices"?}}, "result"?: true}` ——
  这一格给用户填、叫什么、排第几、是不是「主提示词」、只许从这几项里挑;`result` 是「以后只要这张」(ADR 0038 §5);
- 图上:`extra.mosael = {"version": 1, "app"?: {"title", "description", "graph_items": {"seed" | "size" | "runs": {"label"?, "order"}}}}`。

参数键不变:目录里仍是 `<节点 id>.<输入名>`。标记跟着节点走 —— 复制、改节点号、挪进别的工作流都还在,节点删了标记一起没。

**版本只认当前这一版**(`VERSION`)。别的版本按「没有应用表单」处理、报 `unsupported`:读的这一侧不留认旧版的分支,形状
要变时插件随新版本带一个改写那台机器上工作流文件的 op,宿主确认一次改写。没有 `extra.mosael` 的图,节点上的标记不算
(从别的工作流拷过来的节点带着的)。

- `read(ui_graph)` → Marks:文件里写着什么;
- `resolve(marks, api, …)` → (graph.Form, 失效的项):每一项核对一遍 —— 节点还在会跑的那部分图里(graph.live)、那一格还是
  一个能填的字面量(没被拉成连线)、`choices` 还在下拉里;对不上的不进表单,列出来(工作流库里「一键去掉」);
- `apply(ui_graph, app, results)` → 只改 `mosael` 那几处标记的新图(`annotate`,见 workflow_library)。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, replace
from typing import Any

import graph
from lines import ComfyError, say

#: 应用表单的形状是第几版。只认这一版。
VERSION = 1
#: 节点 `properties` 和图 `extra` 里 Mosael 自己的那个键。
KEY = "mosael"
#: 名字、标题、说明最长多少字;一张表最多几项、一项最多几个可选值。宿主先查过一遍,这里写之前再查一遍。
MAX_LABEL = 120
MAX_DESCRIPTION = 1000
MAX_ITEMS = 200
MAX_CHOICES = 1000
MAX_RESULTS = 64
#: 没写 `order` 的项排在最后。
_LAST = 1 << 20


@dataclass(frozen=True)
class Mark:
    """文件里的一项:节点上 `expose` 的一格,或图上 `graph_items` 的一项(`node` 是空串)。"""

    node: str
    input: str
    label: str = ""
    order: int = _LAST
    main: bool = False
    choices: tuple[str, ...] | None = None

    @property
    def key(self) -> str:
        return f"{self.node}.{self.input}" if self.node else self.input


@dataclass(frozen=True)
class Marks:
    """一张工作流里 Mosael 的标记。

    `status`:`none`(没有 `extra.mosael`)/ `ok` / `unsupported`(版本不是这一版,`version` 是文件里写的)。
    `app`:有应用表单(`extra.mosael.app`);没有时 `exposed` 是空的,只可能有结果标记。
    """

    status: str = "none"
    version: Any = None
    app: bool = False
    title: str = ""
    description: str = ""
    exposed: tuple[Mark, ...] = ()
    results: tuple[str, ...] = ()


NONE = Marks()


def _text(value: Any, limit: int) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _mark(node: str, name: str, spec: dict[str, Any]) -> Mark:
    order = spec.get("order")
    choices = spec.get("choices")
    picked = tuple(str(one) for one in choices if isinstance(one, (str, int, float)) and not isinstance(one, bool)) \
        if isinstance(choices, list) else ()
    return Mark(
        node=node,
        input=name,
        label=_text(spec.get("label"), MAX_LABEL),
        order=order if isinstance(order, int) and not isinstance(order, bool) else _LAST,
        main=spec.get("main") is True,
        choices=picked[:MAX_CHOICES] or None,
    )


def read(ui_graph: Any) -> Marks:
    """文件里写着的标记。API 格式的图(没有 `nodes`)没有地方放标记。"""
    if not isinstance(ui_graph, dict) or not isinstance(ui_graph.get("nodes"), list):
        return NONE
    extra = ui_graph.get("extra")
    head = extra.get(KEY) if isinstance(extra, dict) else None
    if head is None:
        return NONE
    version = head.get("version") if isinstance(head, dict) else None
    if not isinstance(head, dict) or isinstance(version, bool) or version != VERSION:
        return Marks(status="unsupported", version=version if isinstance(version, (int, float, str)) else None)
    app = head.get("app") if isinstance(head.get("app"), dict) else None
    exposed: list[Mark] = []
    results: list[str] = []
    for node in ui_graph["nodes"]:
        if not isinstance(node, dict) or node.get("id") is None:
            continue
        props = node.get("properties")
        mark = props.get(KEY) if isinstance(props, dict) else None
        if not isinstance(mark, dict):
            continue
        node_id = str(node["id"])
        if mark.get("result") is True:
            results.append(node_id)
        expose = mark.get("expose")
        if app is not None and isinstance(expose, dict):
            exposed += [_mark(node_id, name, spec) for name, spec in expose.items()
                        if isinstance(name, str) and name and isinstance(spec, dict)]
    if app is not None:
        items = app.get("graph_items")
        exposed += [_mark("", name, spec) for name, spec in (items.items() if isinstance(items, dict) else ())
                    if name in graph.GRAPH_ITEMS and isinstance(spec, dict)]
    exposed.sort(key=lambda one: (one.order, graph._node_order(one.node or "~"), one.input))  # noqa: SLF001
    return Marks(
        status="ok",
        version=VERSION,
        app=app is not None,
        title=_text((app or {}).get("title"), MAX_LABEL),
        description=_text((app or {}).get("description"), MAX_DESCRIPTION),
        exposed=tuple(exposed),
        results=tuple(results),
    )


# ---------------------------------------------------------------------------
# 核对:文件里的标记 → 表单
# ---------------------------------------------------------------------------

_GRAPH_ITEM_NAMES = {"seed": ("种子", "a seed"), "size": ("尺寸", "a size"), "runs": ("跑几遍", "runs")}


def _problem(mark: Mark, item: dict[str, Any] | None, api: dict[str, Any]) -> dict[str, str] | None:
    """这一项为什么对不上(给人看的话,两种语言);对得上是 None。"""
    if not mark.node:
        if item is None:
            zh, en = _GRAPH_ITEM_NAMES.get(mark.input, (mark.input, mark.input))
            return {"zh": f"这张工作流现在没有{zh}这一项了", "en": f"This workflow no longer has {en}."}
        return None
    if item is not None:
        options = [str(one) for one in (item.get("schema") or {}).get("enum") or []]
        gone = [one for one in mark.choices or () if one not in options] if item["kind"] in ("choice", "model") else []
        if gone:
            return {"zh": f"可选值「{gone[0]}」已经不在下拉里了", "en": f"The choice “{gone[0]}” is no longer in the list."}
        return None
    node = api.get(mark.node)
    if not isinstance(node, dict):
        return {"zh": f"节点 #{mark.node} 不在会跑的那部分图里(静音、旁路,或者没接到输出上)",
                "en": f"Node #{mark.node} is not in the part of the graph that runs (muted, bypassed or not connected "
                      "to an output)."}
    inputs = node.get("inputs") or {}
    if mark.input not in inputs:
        return {"zh": f"节点 #{mark.node} 上没有「{mark.input}」这一格了", "en": f"Node #{mark.node} no longer has “{mark.input}”."}
    if isinstance(inputs[mark.input], list):
        return {"zh": f"「{mark.input}」被拉成了连线,不是一个能填的值了",
                "en": f"“{mark.input}” is now connected to a link and is no longer a value to fill in."}
    return {"zh": f"「{mark.input}」不是一个能放进应用表单的项", "en": f"“{mark.input}” can't be part of an app form."}


def resolve(marks: Marks, api: dict[str, Any], object_info: dict[str, Any], titles: dict[str, str] | None = None,
            found: list[dict[str, Any]] | None = None) -> tuple[graph.Form, list[dict[str, Any]]]:
    """文件里的标记 → 这张图的表单,和对不上的那几项(`{key, node, input, label, result?, problem}`)。

    没有标记、或者版本不认识:缺省的应用(全部能填的项)。只有结果标记:缺省的应用 + 标了的结果。有应用表单:作者挑的那几项,
    按作者排的顺序;`main` 只对文字项有意义,`choices` 只对下拉和选模型文件的项有意义(别的项上写了也不理)。
    """
    titles = titles or {}
    found = found if found is not None else graph.items(api, object_info, titles)
    if marks.status != "ok":
        return graph.default_form(found), []
    outputs = {node["node"] for node in graph.output_nodes(api, object_info, titles)}
    invalid: list[dict[str, Any]] = [
        {"key": node, "node": node, "input": "", "label": "", "result": True,
         "problem": {"zh": f"标成结果的节点 #{node} 不再交出东西了(静音、旁路,或者不是输出节点)",
                     "en": f"Node #{node}, marked as the result, no longer produces anything (muted, bypassed or not "
                           "an output node)."}}
        for node in marks.results if node not in outputs
    ]
    results = frozenset(node for node in marks.results if node in outputs)
    if not marks.app:
        return replace(graph.default_form(found), results=results), invalid
    by_key = {item["key"]: item for item in found}
    fields: list[graph.Field] = []
    for mark in marks.exposed:
        item = by_key.get(mark.key)
        problem = _problem(mark, item, api)
        if problem is not None or item is None:
            invalid.append({"key": mark.key, "node": mark.node, "input": mark.input, "label": mark.label,
                            "problem": problem})
            continue
        fields.append(graph.Field(
            item,
            label=mark.label,
            main=mark.main and item["kind"] == "text",
            choices=mark.choices if item["kind"] in ("choice", "model") else None,
        ))
    return graph.Form(tuple(fields), app=True, title=marks.title, description=marks.description,
                      results=results), invalid


def summary(marks: Marks, form: graph.Form, invalid: list[dict[str, Any]], locale: str = "zh") -> dict[str, Any]:
    """给人看的样子:有没有应用表单、版本、标题、说明、文件里的每一项(对不上的带着原因,按读的人的语言)、标成结果的节点。"""
    bad = {one["key"]: say(locale, one["problem"]["zh"], one["problem"]["en"])
           for one in invalid if not one.get("result") and one.get("problem")}
    zh = (locale or "zh").lower().startswith("zh")
    #: 有效的那几项在表单上叫什么(作者起的,没起就是这一项自己的名字),按读的人的语言
    named = {field.key: (field.title.get("zh" if zh else "en", "") if isinstance(field.title, dict) else str(field.title))
             for field in form.fields} if form.app else {}
    return {
        "status": marks.status,
        **({"version": marks.version} if marks.status == "unsupported" and marks.version is not None else {}),
        "app": marks.app,
        "title": marks.title,
        "description": marks.description,
        "items": [
            {"key": mark.key, "node": mark.node, "input": mark.input, "label": mark.label, "main": mark.main,
             **({"title": named[mark.key]} if mark.key in named else {}),
             **({"choices": list(mark.choices)} if mark.choices is not None else {}),
             **({"problem": bad[mark.key]} if mark.key in bad else {})}
            for mark in marks.exposed
        ],
        "results": list(marks.results),
        "invalid": len(invalid),
        "fields": len(form.fields) if form.app else 0,
    }


# ---------------------------------------------------------------------------
# 写:只改 mosael 那几处标记
# ---------------------------------------------------------------------------


def _bad(locale: str, zh: str, en: str) -> ComfyError:
    return ComfyError(say(locale, zh, en))


def apply(ui_graph: dict[str, Any], app: dict[str, Any] | None, results: list[str], locale: str = "zh") -> dict[str, Any]:
    """这张图换上新的标记(返回新图,不改入参):先把每个节点上的 `properties.mosael` 和图上的 `extra.mosael` 摘掉,再按
    `app`(`{title, description, items: [{node, input, label?, main?, choices?}]}`,顺序就是表单的顺序;None = 不要应用表单)
    和 `results`(标成结果的输出节点)写回。**别的一个字都不动** —— 别的扩展写的键、节点的位置、widget 的值照原样。

    只认根图上的节点(子图里面的节点这一版不能放进应用表单);指着不存在的节点、或者形状不对就拒,什么都不写。
    """
    if not isinstance(ui_graph.get("nodes"), list):
        raise _bad(locale, "这不是界面格式的工作流,没有地方放应用表单", "This is not a UI-format workflow, so there is "
                   "nowhere to keep an app form.")
    out = copy.deepcopy(ui_graph)
    nodes = {str(node["id"]): node for node in out["nodes"] if isinstance(node, dict) and node.get("id") is not None}
    for node in nodes.values():
        props = node.get("properties")
        if isinstance(props, dict):
            props.pop(KEY, None)
    extra = out.get("extra")
    if isinstance(extra, dict):
        extra.pop(KEY, None)
    if app is None and not results:
        return out

    def marks_of(node_id: str) -> dict[str, Any]:
        node = nodes.get(node_id)
        if node is None:
            raise _bad(locale, f"这张工作流的根图上没有节点 #{node_id}", f"This workflow has no node #{node_id} at the top level.")
        props = node.setdefault("properties", {})
        if not isinstance(props, dict):
            raise _bad(locale, f"节点 #{node_id} 的 properties 不是一个对象", f"Node #{node_id} has malformed properties.")
        return props.setdefault(KEY, {})

    head: dict[str, Any] = {"version": VERSION}
    if app is not None:
        entries = app.get("items") if isinstance(app.get("items"), list) else []
        if len(entries) > MAX_ITEMS:
            raise _bad(locale, f"一张应用表单最多 {MAX_ITEMS} 项", f"An app form can have at most {MAX_ITEMS} items.")
        graph_items: dict[str, Any] = {}
        body: dict[str, Any] = {"title": _text(app.get("title"), MAX_LABEL),
                                "description": _text(app.get("description"), MAX_DESCRIPTION),
                                "graph_items": graph_items}
        for order, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise _bad(locale, "应用表单里有一项形状不对", "An item in the app form is malformed.")
            node_id, name = str(entry.get("node") or ""), entry.get("input")
            if not isinstance(name, str) or not name:
                raise _bad(locale, "应用表单里有一项没写是哪一格", "An item in the app form doesn't say which input it is.")
            spec: dict[str, Any] = {"order": order}
            label = _text(entry.get("label"), MAX_LABEL)
            if label:
                spec["label"] = label
            if not node_id:
                if name not in graph.GRAPH_ITEMS:
                    raise _bad(locale, f"「{name}」不是图级的项", f"“{name}” is not a graph-level item.")
                graph_items[name] = spec
                continue
            if entry.get("main") is True:
                spec["main"] = True
            choices = entry.get("choices")
            if isinstance(choices, list) and choices:
                spec["choices"] = [str(one) for one in choices[:MAX_CHOICES]]
            marks_of(node_id).setdefault("expose", {})[name] = spec
        head["app"] = body
    for node_id in list(dict.fromkeys(str(one) for one in results))[:MAX_RESULTS]:
        marks_of(node_id)["result"] = True
    if not isinstance(out.get("extra"), dict):
        out["extra"] = {}
    out["extra"][KEY] = head
    return out


__all__ = ["KEY", "Mark", "Marks", "NONE", "VERSION", "apply", "read", "resolve", "summary"]
