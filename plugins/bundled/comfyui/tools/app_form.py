"""表单(ADR 0038 §2、ADR 0045 §7):作者从一张工作流**全部能填的项**(graph.items)里挑出几项、起名、排序、收窄可选值,
存进**这张工作流的 JSON** —— 和别的 ComfyUI 扩展同一个做法(ComfyUI 前端照原样存回节点 `properties` 和图上的 `extra`)。
一张工作流可以有几张表单,各是这张工作流的一个入口(ADR 0045:表单是工作流的入口;完整工作流那个入口永远在)。

存储格式(第 2 版):

- 图上:`extra.mosael = {"version": 2, "forms": [{"id", "title", "description", "graph_items": {"seed" | "size" | "runs":
  {"label"?, "order"}}}, …]}` —— `forms` 的顺序就是表单在各处列出来的顺序,最多 MAX_FORMS 张;
- 节点上:`properties.mosael = {"forms": {<表单 id>: {<输入名>: {"label", "order", "main"?, "choices"?}}}, "result"?: true}`
  —— 每张表单在这个节点上露哪几格、叫什么、排第几、是不是「主提示词」、只许从这几项里挑;`result` 是「以后只要这张」
  (ADR 0038 §5),**按工作流记,不按表单**:它说的是这张图哪个输出是成品,完整入口和每张表单都按它。

**表单 id**:小写字母和数字,1–8 位,只在一张工作流里唯一。第 1 版那唯一一张表单改写过来叫 `app`(它在第 1 版里的键名,
ADR 0045 第一步就把 `#app` / `_app` 定死了);新建的表单由插件起 6 位随机的(不按标题、不按序号:标题会改,序号删一张就让
存着的引用悄悄指向另一张)。

参数键不变:目录里仍是 `<节点 id>.<输入名>`。标记跟着节点走 —— 复制、改节点号、挪进别的工作流都还在,节点删了标记一起没。

**版本只认当前这一版**(`VERSION`)。别的版本按「没有表单」处理、报 `unsupported`:读的这一侧不留认旧版的分支(ADR 0038
§2)。第 1 版能由 `upgrade` 改写过来(插件的 `upgrade_marks`,宿主确认一次整台改写,见 workflow_library);更新的版本是
新插件写的,只能升级插件。没有 `extra.mosael` 的图,节点上的标记不算(从别的工作流拷过来的节点带着的)。

- `read(ui_graph)` → Marks:文件里写着什么;
- `resolve(marks, api, …)` → Resolved:完整工作流的表单、每张表单、失效的项。每一项核对一遍 —— 节点还在会跑的那部分图里
  (graph.live)、那一格还是一个能填的字面量(没被拉成连线)、`choices` 还在下拉里;对不上的不进表单,列出来(工作流库里
  「一键去掉」);
- `apply(ui_graph, forms, results)` → 只改 `mosael` 那几处标记的新图(`annotate`、工作台的 `app_marks`);
- `upgrade(ui_graph)` → 第 1 版改写成这一版的新图,只动 `mosael` 那几处(`upgrade_marks`)。
"""

from __future__ import annotations

import copy
import re
import secrets
import string
from dataclasses import dataclass, field, replace
from typing import Any

import graph
from lines import ComfyError, say

#: 表单的存储格式是第几版。只认这一版。
VERSION = 2
#: 能由 `upgrade` 改写过来的上一版(ADR 0038 那一版:一张图至多一张表单,存在 `extra.mosael.app`)。
LEGACY_VERSION = 1
#: 节点 `properties` 和图 `extra` 里 Mosael 自己的那个键。
KEY = "mosael"
#: 名字、标题、说明最长多少字;一张表最多几项、一项最多几个可选值;一张图最多几张表单。宿主先查过一遍,这里写之前再查一遍。
MAX_LABEL = 120
MAX_DESCRIPTION = 1000
MAX_ITEMS = 200
MAX_CHOICES = 1000
MAX_RESULTS = 64
MAX_FORMS = 20
#: 没写 `order` 的项排在最后。
_LAST = 1 << 20
#: 第 1 版那唯一一张表单改写过来的 id(ADR 0045 §1):它在第 1 版 `extra.mosael` 里的键名。
FORM_ID = "app"
#: 表单 id 的样子:小写字母和数字,1–8 位,只在一张工作流里唯一。
FORM_ID_PATTERN = re.compile(r"^[a-z0-9]{1,8}$")
#: 新表单的 id 几位:智能体工具名 `plugin__<32 位连接 id>__wf_<12 位>_<表单 id>` 不超过 64,6 位是放得下的最长(ADR 0045 §1)。
NEW_ID_LENGTH = 6
_ID_ALPHABET = string.ascii_lowercase + string.digits


@dataclass(frozen=True)
class Mark:
    """文件里的一项:节点上一张表单露的一格,或表单上 `graph_items` 的一项(`node` 是空串)。"""

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
class FormMarks:
    """文件里的一张表单:id、标题、说明、挑的项(按作者排的顺序)。"""

    id: str
    title: str = ""
    description: str = ""
    exposed: tuple[Mark, ...] = ()


@dataclass(frozen=True)
class Marks:
    """一张工作流里 Mosael 的标记。

    `status`:`none`(没有 `extra.mosael`)/ `ok` / `unsupported`(版本不是这一版,`version` 是文件里写的)。
    `forms`:每张表单,按文件里的顺序;`results`:标成结果的节点。`stray`:对不上任何一张表单的标记 —— 节点上指着不存在的
    表单 id、`forms` 里 id 重复或不合规的、超出张数的(不进任何表单,下次保存时清掉)。`legacy_forms`:上一版的文件里那张表单
    的 id(有的话就是 `app`)—— 不读它,只用来说清楚「指着它的地方要升级之后才用得上」。
    """

    status: str = "none"
    version: Any = None
    forms: tuple[FormMarks, ...] = ()
    results: tuple[str, ...] = ()
    stray: tuple[dict[str, str], ...] = ()
    legacy_forms: tuple[str, ...] = ()

    @property
    def upgradable(self) -> bool:
        """是上一版的标记、能由 `upgrade` 改写过来(工作流库里「查看并升级」)。"""
        return self.status == "unsupported" and self.version == LEGACY_VERSION


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


def _ordered(marks: list[Mark]) -> tuple[Mark, ...]:
    return tuple(sorted(marks, key=lambda one: (one.order, graph._node_order(one.node or "~"), one.input)))  # noqa: SLF001


def _version(head: Any) -> Any:
    version = head.get("version") if isinstance(head, dict) else None
    return version if isinstance(version, (int, float, str)) and not isinstance(version, bool) else None


def read(ui_graph: Any) -> Marks:
    """文件里写着的标记。API 格式的图(没有 `nodes`)没有地方放标记。"""
    if not isinstance(ui_graph, dict) or not isinstance(ui_graph.get("nodes"), list):
        return NONE
    extra = ui_graph.get("extra")
    head = extra.get(KEY) if isinstance(extra, dict) else None
    if head is None:
        return NONE
    if not isinstance(head, dict) or _version(head) != VERSION:
        legacy = (FORM_ID,) if _version(head) == LEGACY_VERSION and isinstance(head.get("app"), dict) else ()
        return Marks(status="unsupported", version=_version(head), legacy_forms=legacy)
    stray: list[dict[str, str]] = []
    heads: dict[str, dict[str, Any]] = {}
    for raw in head.get("forms") if isinstance(head.get("forms"), list) else []:
        form_id = raw.get("id") if isinstance(raw, dict) else None
        if not isinstance(form_id, str) or not FORM_ID_PATTERN.match(form_id) or form_id in heads \
                or len(heads) >= MAX_FORMS:
            stray.append({"form": str(form_id)[:20] if form_id is not None else "", "node": ""})
            continue
        heads[form_id] = raw
    exposed: dict[str, list[Mark]] = {form_id: [] for form_id in heads}
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
        per_form = mark.get("forms")
        for form_id, expose in (per_form.items() if isinstance(per_form, dict) else ()):
            if form_id not in exposed:
                stray.append({"form": str(form_id)[:20], "node": node_id})
                continue
            if isinstance(expose, dict):
                exposed[form_id] += [_mark(node_id, name, spec) for name, spec in expose.items()
                                     if isinstance(name, str) and name and isinstance(spec, dict)]
    forms: list[FormMarks] = []
    for form_id, raw in heads.items():
        items = raw.get("graph_items")
        found = exposed[form_id] + [_mark("", name, spec) for name, spec in (items.items() if isinstance(items, dict) else ())
                                    if name in graph.GRAPH_ITEMS and isinstance(spec, dict)]
        forms.append(FormMarks(form_id, _text(raw.get("title"), MAX_LABEL), _text(raw.get("description"), MAX_DESCRIPTION),
                               _ordered(found)))
    return Marks(status="ok", version=VERSION, forms=tuple(forms), results=tuple(results), stray=tuple(stray))


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
    return {"zh": f"「{mark.input}」不是一个能放进表单的项", "en": f"“{mark.input}” can't be part of a form."}


@dataclass(frozen=True)
class Resolved:
    """一张图的几个入口用的表单(ADR 0045):`full` 是完整工作流(全部能填的项 + 标了的结果),`forms` 是表单 id → 那张表单
    (按文件里的顺序),`invalid` 是对不上的那几项(`{form, key, node, input, label, result?, problem}`;标成结果的那几项
    `form` 是空串)。"""

    full: graph.Form
    forms: dict[str, graph.Form] = field(default_factory=dict)
    invalid: list[dict[str, Any]] = field(default_factory=list)


def resolve(marks: Marks, api: dict[str, Any], object_info: dict[str, Any], titles: dict[str, str] | None = None,
            found: list[dict[str, Any]] | None = None) -> Resolved:
    """文件里的标记 → 这张图的几个入口的表单,和对不上的那几项。

    完整工作流永远在:全部能填的项,加上标了的结果。每张表单是作者挑的那几项,按作者排的顺序(`main` 只对文字项有意义,
    `choices` 只对下拉和选模型文件的项有意义,别的项上写了也不理)。没有标记、或者版本不认识:只有完整工作流。
    """
    titles = titles or {}
    found = found if found is not None else graph.items(api, object_info, titles)
    if marks.status != "ok":
        return Resolved(graph.default_form(found))
    outputs = {node["node"] for node in graph.output_nodes(api, object_info, titles)}
    invalid: list[dict[str, Any]] = [
        {"form": "", "key": node, "node": node, "input": "", "label": "", "result": True,
         "problem": {"zh": f"标成结果的节点 #{node} 不再交出东西了(静音、旁路,或者不是输出节点)",
                     "en": f"Node #{node}, marked as the result, no longer produces anything (muted, bypassed or not "
                           "an output node)."}}
        for node in marks.results if node not in outputs
    ]
    results = frozenset(node for node in marks.results if node in outputs)
    full = replace(graph.default_form(found), results=results)
    by_key = {item["key"]: item for item in found}
    forms: dict[str, graph.Form] = {}
    for one in marks.forms:
        fields: list[graph.Field] = []
        for mark in one.exposed:
            item = by_key.get(mark.key)
            problem = _problem(mark, item, api)
            if problem is not None or item is None:
                invalid.append({"form": one.id, "key": mark.key, "node": mark.node, "input": mark.input, "label": mark.label,
                                "problem": problem})
                continue
            fields.append(graph.Field(
                item,
                label=mark.label,
                main=mark.main and item["kind"] == "text",
                choices=mark.choices if item["kind"] in ("choice", "model") else None,
            ))
        forms[one.id] = graph.Form(tuple(fields), app=True, title=one.title, description=one.description, results=results)
    return Resolved(full, forms, invalid)


def summary(marks: Marks, resolved: Resolved, locale: str = "zh", ids: dict[str, dict[str, str]] | None = None) -> dict[str, Any]:
    """给人看的样子:有没有表单、版本(能不能升级)、每张表单(标题、说明、文件里的每一项 —— 对不上的带着原因,按读的人的
    语言 —— 几项有效、几项失效)、标成结果的节点、对不上任何一张表单的标记有几处。`ids` 给了的话,每张表单再带上它的模型 id
    和工具名(`{表单 id: {"model", "tool"}}`,宿主据此数「Mosael 里有几处在用它」)。"""
    zh = (locale or "zh").lower().startswith("zh")
    ids = ids or {}

    def form_out(one: FormMarks) -> dict[str, Any]:
        form = resolved.forms.get(one.id)
        bad = {item["key"]: say(locale, item["problem"]["zh"], item["problem"]["en"])
               for item in resolved.invalid if item["form"] == one.id and item.get("problem")}
        #: 有效的那几项在表单上叫什么(作者起的,没起就是这一项自己的名字),按读的人的语言
        named = {each.key: (each.title.get("zh" if zh else "en", "") if isinstance(each.title, dict) else str(each.title))
                 for each in (form.fields if form is not None else ())}
        return {
            "id": one.id,
            "title": one.title,
            "description": one.description,
            "items": [
                {"key": mark.key, "node": mark.node, "input": mark.input, "label": mark.label, "main": mark.main,
                 **({"title": named[mark.key]} if mark.key in named else {}),
                 **({"choices": list(mark.choices)} if mark.choices is not None else {}),
                 **({"problem": bad[mark.key]} if mark.key in bad else {})}
                for mark in one.exposed
            ],
            "fields": len(form.fields) if form is not None else 0,
            "invalid": sum(1 for item in resolved.invalid if item["form"] == one.id),
            **ids.get(one.id, {}),
        }

    return {
        "status": marks.status,
        **({"version": marks.version} if marks.status == "unsupported" and marks.version is not None else {}),
        "upgradable": marks.upgradable,
        "forms": [form_out(one) for one in marks.forms],
        "results": list(marks.results),
        "invalid": len(resolved.invalid),
        "stray": len(marks.stray),
    }


# ---------------------------------------------------------------------------
# 写:只改 mosael 那几处标记
# ---------------------------------------------------------------------------


def _bad(locale: str, zh: str, en: str) -> ComfyError:
    return ComfyError(say(locale, zh, en))


def new_form_id(taken: set[str]) -> str:
    """一张新表单的 id:6 位随机小写字母和数字,和这张工作流已有的撞了就重抽。"""
    while True:
        candidate = "".join(secrets.choice(_ID_ALPHABET) for _ in range(NEW_ID_LENGTH))
        if candidate not in taken:
            return candidate


def apply(ui_graph: dict[str, Any], forms: list[dict[str, Any]], results: list[str], locale: str = "zh") -> dict[str, Any]:
    """这张图换上新的标记(返回新图,不改入参):先把每个节点上的 `properties.mosael` 和图上的 `extra.mosael` 摘掉,再按
    `forms`(**全部**表单,`[{id?, title, description, items: [{node, input, label?, main?, choices?}]}]`;顺序就是各处列出来
    的顺序,每张表上 `items` 的顺序就是表单的顺序;没给 id 的是新表单,在这里起 id)和 `results`(标成结果的输出节点)
    写回。一张表单都没有、也没标结果就不留 `extra.mosael`。**别的一个字都不动** —— 别的扩展写的键、节点的位置、widget 的值
    照原样。

    只认根图上的节点(子图里面的节点这一版不能放进表单);指着不存在的节点、id 重复或不合规、形状不对就拒,什么都不写。
    """
    if not isinstance(ui_graph.get("nodes"), list):
        raise _bad(locale, "这不是界面格式的工作流,没有地方放表单", "This is not a UI-format workflow, so there is nowhere to "
                   "keep a form.")
    if not isinstance(forms, list) or len(forms) > MAX_FORMS:
        raise _bad(locale, f"一张工作流最多 {MAX_FORMS} 张表单", f"A workflow can have at most {MAX_FORMS} forms.")
    given = [one.get("id") for one in forms if isinstance(one, dict) and one.get("id")]
    if any(not isinstance(one, str) or not FORM_ID_PATTERN.match(one) for one in given) or len(set(given)) != len(given):
        raise _bad(locale, "表单的 id 不合规或重复了", "A form id is malformed or used twice.")
    out = copy.deepcopy(ui_graph)
    nodes = {str(node["id"]): node for node in out["nodes"] if isinstance(node, dict) and node.get("id") is not None}
    for node in nodes.values():
        props = node.get("properties")
        if isinstance(props, dict):
            props.pop(KEY, None)
    extra = out.get("extra")
    if isinstance(extra, dict):
        extra.pop(KEY, None)
    if not forms and not results:
        return out

    def marks_of(node_id: str) -> dict[str, Any]:
        node = nodes.get(node_id)
        if node is None:
            raise _bad(locale, f"这张工作流的根图上没有节点 #{node_id}", f"This workflow has no node #{node_id} at the top level.")
        props = node.setdefault("properties", {})
        if not isinstance(props, dict):
            raise _bad(locale, f"节点 #{node_id} 的 properties 不是一个对象", f"Node #{node_id} has malformed properties.")
        return props.setdefault(KEY, {})

    taken = set(given)
    heads: list[dict[str, Any]] = []
    for form in forms:
        if not isinstance(form, dict):
            raise _bad(locale, "有一张表单形状不对", "A form is malformed.")
        form_id = form.get("id") or new_form_id(taken)
        taken.add(form_id)
        entries = form.get("items") if isinstance(form.get("items"), list) else []
        if len(entries) > MAX_ITEMS:
            raise _bad(locale, f"一张表单最多 {MAX_ITEMS} 项", f"A form can have at most {MAX_ITEMS} items.")
        graph_items: dict[str, Any] = {}
        heads.append({"id": form_id, "title": _text(form.get("title"), MAX_LABEL),
                      "description": _text(form.get("description"), MAX_DESCRIPTION), "graph_items": graph_items})
        for order, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise _bad(locale, "表单里有一项形状不对", "An item in the form is malformed.")
            node_id, name = str(entry.get("node") or ""), entry.get("input")
            if not isinstance(name, str) or not name:
                raise _bad(locale, "表单里有一项没写是哪一格", "An item in the form doesn't say which input it is.")
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
            marks_of(node_id).setdefault("forms", {}).setdefault(form_id, {})[name] = spec
    for node_id in list(dict.fromkeys(str(one) for one in results))[:MAX_RESULTS]:
        marks_of(node_id)["result"] = True
    if not isinstance(out.get("extra"), dict):
        out["extra"] = {}
    out["extra"][KEY] = {"version": VERSION, "forms": heads}
    return out


def upgrade(ui_graph: Any) -> dict[str, Any] | None:
    """上一版(第 1 版)的标记改写成这一版,交回新图(不改入参);不是第 1 版的图是 None(用不着改)。

    **只动 `mosael` 那几处**,而且就地换值(键在原来的位置,`json_style.dumps_like` 写回时别的字节一个不变):第 1 版有表单的,
    图上写成 `forms: [{"id": "app", …原来那张…}]`、节点上的 `expose` 换成 `forms.app`;只有结果标记的,`forms` 是空的。
    `result` 原样。第 1 版里没有表单时节点上残留的 `expose` 本来就不算(从别的工作流拷过来的节点带着的),去掉。
    """
    if not isinstance(ui_graph, dict) or not isinstance(ui_graph.get("nodes"), list):
        return None
    extra = ui_graph.get("extra")
    head = extra.get(KEY) if isinstance(extra, dict) else None
    if not isinstance(head, dict) or _version(head) != LEGACY_VERSION:
        return None
    out = copy.deepcopy(ui_graph)
    app = head.get("app") if isinstance(head.get("app"), dict) else None
    out["extra"][KEY] = {"version": VERSION, "forms": [{"id": FORM_ID, **{k: v for k, v in app.items() if k != "id"}}]
                         if app is not None else []}
    for node in out["nodes"]:
        props = node.get("properties") if isinstance(node, dict) else None
        mark = props.get(KEY) if isinstance(props, dict) else None
        if not isinstance(mark, dict) or "expose" not in mark:
            continue
        rewritten: dict[str, Any] = {}
        for key, value in mark.items():
            if key != "expose":
                rewritten[key] = value
            elif app is not None and isinstance(value, dict) and value:
                rewritten["forms"] = {FORM_ID: value}
        if rewritten:
            props[KEY] = rewritten
        else:
            del props[KEY]
    return out


__all__ = ["FORM_ID", "FORM_ID_PATTERN", "FormMarks", "KEY", "LEGACY_VERSION", "MAX_FORMS", "Mark", "Marks", "NONE",
           "Resolved", "VERSION", "apply", "new_form_id", "read", "resolve", "summary", "upgrade"]
