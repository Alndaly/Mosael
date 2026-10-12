"""ComfyUI 保存的工作流(UI 图)→ `/prompt` 吃的 API 图。

两者的转换在 ComfyUI 前端的 `graphToPrompt`(src/utils/executionUtil.ts)和 `ExecutableNodeDTO`
(src/lib/litegraph/src/subgraph/ExecutableNodeDTO.ts)里,后端没有接口。这里照它们的语义复现,
逐条对着前端的行为:

- **widget 的值按节点定义排**:前端按 object_info 的输入顺序(有 `input_order` 就按它)建 widget,
  `widgets_values` 是这些 widget 的值按下标排好的。老版本前端存的图里 `node.inputs` 只列连线和
  「转成输入」的 widget —— 只按 `node.inputs` 数 widget 的话,一张老图的 KSampler 一个值都拿不到;
- 一个 widget 在 `widgets_values` 里可能多占几格:INT 的 seed / noise_seed(或声明了
  `control_after_generate` 的输入)后面跟着「生成后怎样」那一格;读素材的节点在必填输入之后多一个上传按钮
  (`upload`),音频节点再多一个播放器(`audioUI`);
- `widgets_values` 也可能是按名字存的对象(VHS 的节点就是这样存的);
- 值是数组的 widget 要包成 `{"__value__": [...]}` —— 数组在 API 图里表示连线;
- **muted(mode 2)的节点**不进图,连到它的输入去掉(是 widget 的就留着 widget 自己的值);
- **bypassed(mode 4)的节点**不进图,但它是透明的:下游从它那儿要的输出,改接到它身上类型对得上的那个
  输入的上游(先同一个序号,再同类型,再兼容的类型)—— 用户关掉一个 LoRA 加载器,模型照样流下去;
- 只在前端存在的节点(注释、Reroute、PrimitiveNode、KJNodes 的 Get / Set …)不进图:Reroute 透传、
  PrimitiveNode 把自己的值写进下游那一格、GetNode 找同名的 SetNode 接它的上游。后端真有的节点
  (`PrimitiveInt` 这类,object_info 里有)照常进图;
- **子图**(新版前端的 subgraph,`definitions.subgraphs`)展开成里面的节点,id 是「外层节点 id:里层节点 id」
  —— 和前端提交时、ComfyUI 在进度消息里用的执行 id 同一套写法;子图的输入口接回外面连进来的线,外面没连线
  的,用子图节点上那一格(提升出来的 widget)的值;
- 连线两种写法都认:老的数组 `[id, 源节点, 源槽, 目标节点, 目标槽, 类型]` 和新的对象(子图里就是这种)。

转换是**尽力而为**:认不出的非常规工作流,用户可以在 ComfyUI 里「导出 (API)」,把那份 JSON 导进工作流库(workflow_import
会把 API 格式转成界面格式)。
"""

from __future__ import annotations

import copy
from typing import Any

from lines import ComfyError, say

#: 前端节点的 mode:2 = 静音(不跑,下游断开)、4 = 旁路(不跑,下游从它的输入直通)。
MODE_NEVER = 2
MODE_BYPASS = 4

#: 只在前端存在、不进 API 图的节点。**只在 object_info 里没有它时**才当它是前端节点 ——
#: 后端真有的同名节点照常进图。
_REROUTES = frozenset({"Reroute", "Reroute (rgthree)"})
_PRIMITIVE = "PrimitiveNode"
_GET, _SET = "GetNode", "SetNode"
#: rgthree 那几个是它前端里的虚拟节点(`isVirtualNode`:继承 RgthreeBaseVirtualNode 的,外加它自己的 Reroute)——
#: 管别的节点开关的 Relay / Repeater、Collector 也在里面,子图里常见,漏一个整张图就被 ComfyUI 以「节点不存在」拒掉。
_FRONTEND_ONLY = _REROUTES | {
    _PRIMITIVE, _GET, _SET, "Note", "MarkdownNote", "Label (rgthree)", "Bookmark (rgthree)",
    "Fast Groups Bypasser (rgthree)", "Fast Groups Muter (rgthree)", "Fast Bypasser (rgthree)",
    "Fast Muter (rgthree)", "Fast Actions Button (rgthree)", "Mute / Bypass Relay (rgthree)",
    "Mute / Bypass Repeater (rgthree)", "Node Collector (rgthree)", "Node Combiner (rgthree)",
    "Random Unmuter (rgthree)", "Power Conductor (rgthree)",
}

#: 前端给这些类型建 widget(src/scripts/widgets.ts 的 ComfyWidgets 加上上传、音频的扩展)。不在这里的
#: 类型是连线的插口(MODEL、IMAGE…);自定义扩展的 widget 类型从存下来的 `node.inputs` 里的 `widget` 标记认。
WIDGET_TYPES = frozenset({
    "INT", "FLOAT", "BOOLEAN", "STRING", "MARKDOWN", "COMBO", "IMAGEUPLOAD", "COLOR", "IMAGECOMPARE",
    "BOUNDING_BOX", "BOUNDING_BOXES", "CHART", "GALLERIA", "PAINTER", "COMPOSITOR", "TEXTAREA", "CURVE", "RANGE",
    "VIDEO_EDIT", "RESOLUTION_PREVIEW", "COLORS", "AUDIO_UI", "AUDIOUPLOAD",
})
#: 老规矩:名字叫这两个的 INT 没写 control_after_generate 也带「生成后怎样」那一格(useIntWidget)。
_LEGACY_SEEDS = ("seed", "noise_seed")
#: 这几种选项说明一个下拉读的是 input 目录里的文件:前端在必填输入之后给它加一个上传按钮(uploadImage.ts)。
_MEDIA_UPLOAD_OPTIONS = ("image_upload", "video_upload", "animated_image_upload")
#: 前端给这些音频节点加一个播放器 widget(uploadAudio.ts),同样排在必填输入之后。
_AUDIO_UI_CLASSES = frozenset({"LoadAudio", "SaveAudio", "PreviewAudio", "SaveAudioMP3", "SaveAudioOpus",
                               "SaveAudioAdvanced"})
#: 只在前端的 widget:它们在 `widgets_values` 里占位置,但不进 API 图。
#: ComfyUI 新式节点(V3)的模板输入:定义里只有**一格**,展开出来的具体输入叫 `名字.子名`
#: (`sampling_mode.temperature`、`values.a`……)。读 `widgets_values` 时它们是**占位置的 widget**,
#: 而且位置就在模板那一格**后面** —— 排到最后会把后面的值全挤错位(真机:TextGenerate 的
#: temperature/top_k/… 顶掉了 thinking/use_default_template/mtp)。
_V3_MATCH, _V3_AUTOGROW, _V3_DYNAMIC = "COMFY_MATCHTYPE_V3", "COMFY_AUTOGROW_V3", "COMFY_DYNAMICCOMBO_V3"
_V3_TEMPLATES = (_V3_AUTOGROW, _V3_DYNAMIC)

_FRONTEND_WIDGETS = frozenset({"upload", "audioUI"})

#: 转换时写进 `_meta` 的:每个带「生成后怎样」的 widget 存着的设定(randomize / fixed / increment / decrement)。
#: API 图里没有这一格(它是前端的行为),可「这张图的种子每次换不换」只有它说得清。
CONTROLS = "control_after_generate"
#: 写进 `_meta` 的:哪几格下拉存的值已经不在选项里、按定义缺省复位过(见 _restore_stale_combo)。
RESET_COMBOS = "reset_stale_combos"
#: 写进 `_meta` 的:这一格在**画布上**叫什么(`<输入名> → <一句名字>`,见 `_own_labels`)。API 图里没有这一格
#: (它是界面上的一个显示名),可「维护者在 ComfyUI 右侧 Parameters 里把 `mask_expand_pixels` 叫成『遮罩像素扩展』」
#: 只有它说得清 —— 取名时排在 `/i18n` 前面(见 labels.describe)。
INPUT_LABELS = "input_labels"

#: 子图输入口 / 输出口的节点 id 缺省值(前端的 SUBGRAPH_INPUT_ID / SUBGRAPH_OUTPUT_ID)。
_SUBGRAPH_INPUT, _SUBGRAPH_OUTPUT = -10, -20
#: 子图最多套几层(一个子图里又放了它自己 —— 坏文件 —— 不该让转换转到栈溢出)。
_MAX_DEPTH = 32


def is_api_graph(graph: Any) -> bool:
    """已经是 API 格式了吗(「导出 (API)」出来的那种:节点 id → {class_type, inputs})。"""
    return (
        isinstance(graph, dict)
        and bool(graph)
        and "nodes" not in graph
        and all(isinstance(node, dict) and "class_type" in node for node in graph.values())
    )


def titles_of(api: dict[str, Any]) -> dict[str, str]:
    """节点 id → 界面上的名字(`_meta.title`:用户起的标题,没起就是类名)。转换时写进去,导出的 API 图自己带着。"""
    titles: dict[str, str] = {}
    for node_id, node in api.items():
        meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
        titles[str(node_id)] = str(meta.get("title") or node.get("class_type") or "")
    return titles


def to_api(ui_graph: dict[str, Any], object_info: dict[str, Any], locale: str = "zh") -> dict[str, Any]:
    """UI 图 → API 图。已经是 API 图的原样(拷一份)交回。"""
    if is_api_graph(ui_graph):
        return copy.deepcopy(ui_graph)
    return _Converter(ui_graph, object_info, locale).run()


def widget_values(node: dict[str, Any], object_info: dict[str, Any]) -> dict[str, Any]:
    """一个界面格式节点上各个 widget 的值,按名字 —— 和转成 API 图时同一套认法(`widgets_values` 按定义里 widget 的先后,
    「生成后怎样」那一格跳过,存的值缺了用定义里的缺省值)。这台 ComfyUI 上没有这类节点时只认存下来标着 widget 的那几格。
    诊断(diagnose)、画布摘要(canvas)用它。"""
    scope = _Scope({"nodes": [node]}, (), None)
    values = _Converter({"nodes": [node]}, object_info, "zh")._widget_values(_Node(scope, node), {})
    return {name: value["__value__"] if isinstance(value, dict) and set(value) == {"__value__"} else value
            for name, value in values.items()}


def connectable(output_type: Any, input_type: Any) -> bool:
    """一个输出能不能连到一个输入(LiteGraph 的判法,见 _valid_connection)。"""
    return _valid_connection(output_type, input_type)


def widget_layout(node: dict[str, Any], object_info: dict[str, Any]) -> list[tuple[str, Any, int]]:
    """一个界面格式节点的 widget 在 `widgets_values` 里怎么排:(名字, 定义, 后面多占几格)—— 和转换时同一套(改画布时
    往 `widgets_values` 里写一格、给新节点排一份,见 canvas_edit)。只在前端的那几格(上传按钮、播放器)也在里面。"""
    scope = _Scope({"nodes": [node]}, (), None)
    return _Converter({"nodes": [node]}, object_info, "zh")._widget_specs(_Node(scope, node))


def widget_default(definition: Any) -> tuple[bool, Any]:
    """一格 widget 的缺省值(前端建节点时给的):(有没有, 值)。"""
    return _Converter._default(definition)


# ---------------------------------------------------------------------------
# 一层图:根图,或展开到某个子图节点里的那一份
# ---------------------------------------------------------------------------


def _links(raw: Any) -> dict[Any, tuple[Any, int, Any, int, Any]]:
    """连线 id → (源节点, 源槽, 目标节点, 目标槽, 类型)。数组和对象两种写法都认。"""
    found: dict[Any, tuple[Any, int, Any, int, Any]] = {}
    for link in raw or []:
        if isinstance(link, list) and len(link) >= 5:
            found[link[0]] = (link[1], _slot(link[2]), link[3], _slot(link[4]), link[5] if len(link) > 5 else None)
        elif isinstance(link, dict) and "id" in link:
            found[link["id"]] = (link.get("origin_id"), _slot(link.get("origin_slot")), link.get("target_id"),
                                 _slot(link.get("target_slot")), link.get("type"))
    return found


def _slot(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _same(left: Any, right: Any) -> bool:
    """两个节点 id 是不是同一个(存下来的有的是数字、有的是字符串)。"""
    return left is not None and right is not None and str(left) == str(right)


class _Scope:
    def __init__(self, raw: dict[str, Any], path: tuple[str, ...], instance: "_Node | None") -> None:
        self.nodes: dict[str, dict[str, Any]] = {}
        for node in raw.get("nodes") or []:
            if isinstance(node, dict) and node.get("id") is not None:
                self.nodes[str(node["id"])] = node
        self.links = _links(raw.get("links"))
        self.path = path
        #: 这一层是哪个子图节点展开出来的(根图是 None)
        self.instance = instance
        self.input_node = (raw.get("inputNode") or {}).get("id", _SUBGRAPH_INPUT)
        self.output_node = (raw.get("outputNode") or {}).get("id", _SUBGRAPH_OUTPUT)


class _Node:
    def __init__(self, scope: _Scope, raw: dict[str, Any]) -> None:
        self.scope = scope
        self.raw = raw
        self.id = ":".join((*scope.path, str(raw.get("id"))))
        self.type = str(raw.get("type") or "")
        self.mode = raw.get("mode")

    @property
    def inputs(self) -> list[dict[str, Any]]:
        return [entry for entry in self.raw.get("inputs") or [] if isinstance(entry, dict)]

    @property
    def outputs(self) -> list[dict[str, Any]]:
        return [entry for entry in self.raw.get("outputs") or [] if isinstance(entry, dict)]


def _valid_connection(left: Any, right: Any) -> bool:
    """LiteGraph.isValidConnection:`*` / 空认一切,逗号分开的类型有交集就行。"""
    if left in ("", "*", 0, None) or right in ("", "*", 0, None) or left == right:
        return True
    left_types = {one.strip().lower() for one in str(left).split(",")}
    right_types = {one.strip().lower() for one in str(right).split(",")}
    return bool(left_types & right_types)


def _wrap(value: Any) -> Any:
    """数组在 API 图里表示连线:值本身是数组的 widget 包一层(后端执行时自己拆开)。"""
    return {"__value__": value} if isinstance(value, list) else value


def _own_labels(node: _Node) -> dict[str, str]:
    """画布上这个节点**每一格写着的名字**:输入名 → 那一句(`inputs[].label`)。

    这一格是**界面上改出来的名字**:维护者在 ComfyUI 右侧「Parameters」里直接改那一格的标题(前端的
    `WidgetItem.vue` → `widgetUtil.renameWidget` 写 `input.label`),随工作流一起存下来;节点包自己给了
    `display_name` 时前端也往这里写(见 litegraphService 的 `addInputWidget`)。同一个输入名在不同节点上
    可以是不同的名字,所以它挂在**节点**上,不是挂在节点类上。

    和输入名一模一样的那一句**不是名字,是身份**(真机上存下来的过半都是这种:`MiniMaxH3SigmaShift` 的
    `model` 存的就是 `"model"`):收进来只会让 `mask_expand_pixels` 顶掉「Mask expand pixels」。空白的、不是
    一句字符串的也不收。
    """
    found: dict[str, str] = {}
    for entry in node.inputs:
        name = entry.get("name")
        label = entry.get("label")
        if not isinstance(name, str) or not name or not isinstance(label, str):
            continue
        label = label.strip()
        if label and label != name:
            found[name] = label
    return found


class _Converter:
    def __init__(self, ui_graph: dict[str, Any], object_info: dict[str, Any], locale: str) -> None:
        self.ui = ui_graph
        self.object_info = object_info or {}
        self.locale = locale
        self.definitions: dict[str, dict[str, Any]] = {}
        self._collect_definitions(ui_graph)
        #: 子图节点的执行 id → 它展开出来的那一层
        self.children: dict[str, _Scope] = {}
        self.api: dict[str, Any] = {}

    def _collect_definitions(self, graph: dict[str, Any], depth: int = 0) -> None:
        if depth > _MAX_DEPTH:
            return
        for definition in ((graph.get("definitions") or {}).get("subgraphs") or []):
            if isinstance(definition, dict) and definition.get("id"):
                self.definitions.setdefault(str(definition["id"]), definition)
                self._collect_definitions(definition, depth + 1)

    # --- 走一遍 -------------------------------------------------------------

    def run(self) -> dict[str, Any]:
        self._reject_group_nodes()
        self._walk(_Scope(self.ui, (), None), 0)
        # 连到不在图里的节点的输入去掉(前端 graphToPrompt 最后那一步)
        for node in self.api.values():
            inputs = node["inputs"]
            for name in [name for name, value in inputs.items()
                         if isinstance(value, list) and len(value) == 2 and str(value[0]) not in self.api]:
                del inputs[name]
        return self.api

    def _reject_group_nodes(self) -> None:
        """旧式的「组节点」(workflow>名字)已经被子图取代,前端自己也只在载入时把它转成子图。"""
        groups = ((self.ui.get("extra") or {}).get("groupNodes") or {})
        for node in self.ui.get("nodes") or []:
            kind = str((node or {}).get("type") or "") if isinstance(node, dict) else ""
            if kind.startswith(("workflow>", "workflow/")) and (not self.object_info or kind not in self.object_info):
                name = kind.split(">", 1)[-1].split("/", 1)[-1]
                if not groups or name in groups:
                    raise ComfyError(say(
                        self.locale,
                        f"这张工作流用了旧式的「组节点」({name}):请在 ComfyUI 里把它转成子图后再保存",
                        f"This workflow uses a legacy group node ({name}). Convert it to a subgraph in ComfyUI and save again.",
                    ))

    def _walk(self, scope: _Scope, depth: int) -> None:
        if depth > _MAX_DEPTH:
            raise ComfyError(say(self.locale, "子图套得太深(或者套了它自己)", "Subgraphs are nested too deeply (or contain themselves)"))
        for raw in scope.nodes.values():
            node = _Node(scope, raw)
            if node.mode in (MODE_NEVER, MODE_BYPASS):
                continue
            if node.type in self.definitions:
                child = self._child(node)
                self._walk(child, depth + 1)
                continue
            if self._frontend_only(node):
                continue
            self.api[node.id] = self._emit(node)

    def _child(self, node: _Node) -> _Scope:
        child = self.children.get(node.id)
        if child is None:
            child = _Scope(self.definitions[node.type], (*node.scope.path, str(node.raw.get("id"))), node)
            self.children[node.id] = child
        return child

    def _frontend_only(self, node: _Node) -> bool:
        return node.type in _FRONTEND_ONLY and node.type not in self.object_info

    # --- 一个节点 -----------------------------------------------------------

    def _emit(self, node: _Node) -> dict[str, Any]:
        controls: dict[str, str] = {}
        resets: list[str] = []
        inputs = self._widget_values(node, controls, resets)
        for entry in node.inputs:
            name = entry.get("name")
            if not name or entry.get("link") is None:
                continue
            resolved = self._resolve_input(node, entry, set())
            if resolved is None:
                continue  # 上游被静音 / 断了:是 widget 的留着它自己的值,是插口的就不连
            if resolved[0] == "value":
                inputs[name] = _wrap(resolved[1])
                if len(resolved) > 2 and resolved[2]:
                    controls[name] = resolved[2]  # PrimitiveNode 自己的「生成后怎样」说了算
            else:
                inputs[name] = [resolved[1], resolved[2]]
        meta: dict[str, Any] = {"title": str(node.raw.get("title") or node.type)}
        labels = _own_labels(node)
        if labels:
            meta[INPUT_LABELS] = labels
        if controls:
            # 后端不看 _meta;插件据此在没给种子时照工作流的设定办(见 graph.fill)
            meta[CONTROLS] = controls
        if resets:
            #: 哪几格的下拉存的是节点包上一版的值、已经按定义缺省复位(和 ComfyUI 页面的行为一致):
            #: 留在图上是个痕迹,不至于「跑出来的东西和文件里存的不一样」而没人说得清为什么。
            meta[RESET_COMBOS] = resets
        return {"class_type": node.type, "inputs": inputs, "_meta": meta}

    def _widget_specs(self, node: _Node) -> list[tuple[str, Any, int]]:
        """这个节点的 widget,按它们在 `widgets_values` 里的顺序:(名字, 定义, 后面多占几格)。

        顺序**和前端一致**:定义里声明的格子按定义顺序,其中 V3 模板(`COMFY_DYNAMICCOMBO_V3` /
        `COMFY_AUTOGROW_V3`)展开出来的子输入**紧跟在模板那一格后面**(名字前缀 `模板名.`),
        定义里没有、文件里却标着 widget 的(动态加出来的)排在最后。

        此前子输入被排到最后,于是模板之后的值整体错位(真机:TextGenerate 的 sampling_mode.temperature
        顶掉了 thinking,mtp 拿到了 top_p 的 0.95)。
        """
        marked = [str(entry.get("name")) for entry in node.inputs if "widget" in entry and entry.get("name")]
        spec = self.object_info.get(node.type)
        if not isinstance(spec, dict):
            # 这台 ComfyUI 上没有这个节点(自定义节点没装):只能信存下来的 widget 标记,提交时 ComfyUI 会说它缺什么
            types = {str(entry.get("name")): entry.get("type") for entry in node.inputs}
            return [(name, None, 1 if types.get(name) == "INT" and name in _LEGACY_SEEDS else 0) for name in marked]
        declared = spec.get("input") or {}
        order = spec.get("input_order") if isinstance(spec.get("input_order"), dict) else {}
        found: list[tuple[str, Any, int]] = []
        seen: set[str] = set()

        def add(name: str, definition: Any) -> None:
            found.append((name, definition, self._extra_slots(name, definition) if definition is not None else 0))
            seen.add(name)

        for section in ("required", "optional"):
            defs = declared.get(section) or {}
            if not isinstance(defs, dict):
                continue
            names = [one for one in (order.get(section) or []) if one in defs] or list(defs)
            names += [one for one in defs if one not in names]
            for name in names:
                definition = defs[name]
                if name in marked or self._is_widget(definition):
                    add(name, definition)
                    #: 这一格是模板时,紧跟它后面、以 `名字.` 开头的标记就是它这次展开出来的子输入。
                    for sub in self._v3_children(marked, name):
                        if sub not in seen:
                            add(sub, self._definition_of(node.type, sub))
            if section == "required":
                if node.type in _AUDIO_UI_CLASSES:
                    add("audioUI", None)
                if any(self._uploads(definition) for definition in defs.values()):
                    add("upload", None)
        # 定义里没有、存下来却标着 widget 的(动态加出来的输入):按文件顺序排在最后
        for name in marked:
            if name not in seen:
                add(name, None)
        return found

    @staticmethod
    def _v3_children(marked: list[str], base: str) -> list[str]:
        """文件里紧跟在 `base` 之后、名字是 `base.子名` 的那几格 —— V3 模板这次展开出来的子输入。"""
        children: list[str] = []
        if base not in marked:
            return children
        prefix = f"{base}."
        for name in marked[marked.index(base) + 1:]:
            if not name.startswith(prefix):
                break
            children.append(name)
        return children

    def _definition_of(self, node_type: str, name: str) -> Any:
        """一个 widget 名字在这台 ComfyUI 上的定义:顶层声明里的,或者 V3 模板展开出来的。

        `sampling_mode.temperature` 这种在顶层声明里找不到 —— 它在 `sampling_mode` 那一格
        的选项里。认不出来就当它已经不存在了(节点包删掉过这个格子):那个值要**跳过**,
        不能让后面的值往前挤一格。
        """
        spec = self.object_info.get(node_type)
        declared = (spec or {}).get("input") if isinstance(spec, dict) else None
        if not isinstance(declared, dict):
            return None
        for section in ("required", "optional"):
            defs = declared.get(section) or {}
            if isinstance(defs, dict) and name in defs:
                return defs[name]
        base, _, rest = name.partition(".")
        if not rest:
            return None
        base_definition = None
        for section in ("required", "optional"):
            defs = declared.get(section) or {}
            if isinstance(defs, dict) and base in defs:
                base_definition = defs[base]
                break
        kind = base_definition[0] if isinstance(base_definition, list) and base_definition else None
        options = self._options(base_definition)
        if kind == _V3_DYNAMIC:
            for option in options.get("options") or []:
                found = ((option.get("inputs") or {}).get("required") or {})
                found.update((option.get("inputs") or {}).get("optional") or {})
                if rest in found:
                    return found[rest]
            return None
        if kind == _V3_AUTOGROW:
            template = ((options.get("template") or {}).get("input") or {})
            merged = {**(template.get("required") or {}), **(template.get("optional") or {})}
            return merged.get(rest)
        return None

    @staticmethod
    def _options(definition: Any) -> dict[str, Any]:
        if isinstance(definition, list) and len(definition) > 1 and isinstance(definition[1], dict):
            return definition[1]
        return {}

    def _is_widget(self, definition: Any) -> bool:
        if not isinstance(definition, list) or not definition:
            return False
        options = self._options(definition)
        if options.get("forceInput"):
            return False
        kind = options.get("widgetType") or definition[0]
        return isinstance(kind, list) or kind in WIDGET_TYPES

    def _uploads(self, definition: Any) -> bool:
        options = self._options(definition)
        return any(options.get(flag) for flag in _MEDIA_UPLOAD_OPTIONS) or bool(options.get("audio_upload"))

    @staticmethod
    def _v2_combo_options(definition: Any) -> list[str] | None:
        """**新版下拉**的选项(`["COMBO", {"options": [...]}]`)。老式的(`[["a.safetensors", ...]]`)返回 None ——
        两者在 ComfyUI 前端里行为不同,不能一样对待(见 _restore_stale_combo)。"""
        if not isinstance(definition, list) or len(definition) < 2 or definition[0] != "COMBO":
            return None
        if not isinstance(definition[1], dict):
            return None
        options = definition[1].get("options")
        return [str(one) for one in options] if isinstance(options, list) else None

    def _restore_stale_combo(self, definition: Any, value: Any) -> tuple[Any, bool]:
        """**新版下拉**里存的值已经不在选项里了:按节点定义里的缺省值复位 —— 和 ComfyUI 自己的页面一样。

        实测(2026-10-11,真机 8120):这种下拉在页面上渲染后会把不认识的值换回定义里的默认值(工作流文件里
        存着上一版节点包的占位符,工作台照样跑得通就是这个原因);而**老式列表下拉**(模型文件那种)前端
        原样提交、后端回 `Value not in list` —— 那种我们自己会在提交前说清缺什么(见 run.preflight),
        不能在这里悄悄换一个模型。

        返回 (值, 是否复位过)。
        """
        options = self._v2_combo_options(definition)
        if options is None or not isinstance(value, str) or value in options:
            return value, False
        default = self._options(definition).get("default")
        if isinstance(default, str) and default in options:
            return default, True
        return (options[0] if options else value), True

    def _extra_slots(self, name: str, definition: Any) -> int:
        """「生成后怎样」那一格:显式写了就照它,INT 的 seed / noise_seed 没写也有(老规矩)。"""
        options = self._options(definition)
        control = options.get("control_after_generate")
        if control is None:
            kind = definition[0] if isinstance(definition, list) and definition else None
            return 1 if kind == "INT" and name in _LEGACY_SEEDS else 0
        return 1 if control else 0

    @staticmethod
    def _default(definition: Any) -> tuple[bool, Any]:
        if not isinstance(definition, list) or not definition:
            return False, None
        options = _Converter._options(definition)
        if "default" in options:
            return True, options["default"]
        choices = definition[0] if isinstance(definition[0], list) else options.get("options")
        if isinstance(choices, list) and choices:
            return True, choices[0]
        return False, None

    def _widget_values(self, node: _Node, controls: dict[str, str],
                       resets: list[str] | None = None) -> dict[str, Any]:
        """widget 的值;顺手把「生成后怎样」那一格(randomize / fixed / …)记进 `controls`。"""
        stored = node.raw.get("widgets_values")
        values: dict[str, Any] = {}
        index = 0
        specs = self._widget_specs(node)
        in_file = {str(entry.get("name")) for entry in node.inputs if "widget" in entry}
        for name, definition, extra in specs:
            if isinstance(stored, dict):
                present, value = name in stored, stored.get(name)
            else:
                present = isinstance(stored, list) and index < len(stored)
                value = stored[index] if present else None
                if extra and isinstance(stored, list) and index + 1 < len(stored) and isinstance(stored[index + 1], str):
                    controls[name] = stored[index + 1]
                index += 1 + extra
            if name in _FRONTEND_WIDGETS:
                continue
            if not present or value is None:
                # 定义后来多了一个输入(节点升级过):前端载入时给它的是缺省值
                present, value = self._default(definition)
                if not present:
                    continue
            value, restored = self._restore_stale_combo(definition, value)
            if restored and resets is not None:
                resets.append(name)
            values[name] = _wrap(value)
        #: 定义里有、文件里没有的(节点包新加了一格):它不是这些值里的一个,用定义里的缺省值 ——
        #: 此前按位置硬走,新加的格子会顶掉下一个值(和上面 V3 那张错位是同一类)。文件自己标着的
        #: 格子(哪怕当前定义里查不到,如 API 里有值的 V3 子输入)照旧算数:它才是这些值的作者。
        for name, definition, _extra in self._widget_specs(node):
            if not in_file or name in in_file or name in values or name in _FRONTEND_WIDGETS:
                continue
            present, value = self._default(definition)
            if present:
                values[name] = _wrap(value)
        return values

    # --- 顺着连线找到真正的上游 ----------------------------------------------

    def _resolve_input(self, node: _Node, entry: dict[str, Any], visited: set[tuple[str, str, int]],
                       wanted: Any = None) -> tuple | None:
        """一个输入接到哪儿:("link", 执行 id, 槽位) / ("value", 值) / None(没接上)。"""
        link = node.scope.links.get(entry.get("link"))
        if link is None:
            return None
        origin, origin_slot = link[0], link[1]
        wanted = wanted if wanted is not None else (entry.get("type") or link[4])
        scope = node.scope
        if scope.instance is not None and _same(origin, scope.input_node):
            return self._from_subgraph_input(scope.instance, origin_slot, visited)
        source = scope.nodes.get(str(origin))
        if source is None:
            return None
        return self._resolve_output(_Node(scope, source), origin_slot, wanted, visited)

    def _from_subgraph_input(self, instance: _Node, slot: int, visited: set) -> tuple | None:
        """子图里接在输入口第 `slot` 格(子图定义的 `inputs` 里的第几个)上的:外面连了线就顺着外面走,没连就用子图节点上
        那一格(提升出来的 widget)的值。

        子图节点自己的 `inputs` **按名字找、不按下标**:前端导出的图(`graphToPrompt` 的 workflow —— 工作台导出的画布、
        「导出」的 JSON、PNG 里带的)会把没连线、没起名的 widget 输入口删掉(前端的 compressWidgetInputSlots),下标就
        对不上了 —— 此前按下标取,取不到就落回子图里那个节点自己存的旧值:MiniMax H3 那张选的 UNET 是
        minimaxH3INT8INT4_fl2vaINT8Pruned,缺失项却报模板默认的 minimax_h3_fl2va_pruned_int8_convrot。
        `widgets_values` 不压,按子图定义里**是 widget 的那几格**排:子图节点上标着 widget 的,或者被删掉了的(被删的只会是
        没连线的 widget)。"""
        definition = self.definitions.get(instance.type) or {}
        declared = [one for one in definition.get("inputs") or [] if isinstance(one, dict)]
        if slot >= len(declared):
            return None
        name = declared[slot].get("name")
        entries = {one.get("name"): one for one in instance.inputs if one.get("name")}
        entry = entries.get(name)
        if entry is not None and entry.get("link") is not None:
            return self._resolve_input(instance, entry, visited)
        if entry is not None and "widget" not in entry:
            return None  # 是插口,外面没连
        stored = instance.raw.get("widgets_values")
        if isinstance(stored, dict):
            return ("value", stored[name]) if stored.get(name) is not None else None
        promoted = [one.get("name") for one in declared
                    if entries.get(one.get("name")) is None or "widget" in entries[one.get("name")]]
        index = promoted.index(name)
        if isinstance(stored, list) and index < len(stored) and stored[index] is not None:
            return ("value", stored[index])
        return None  # 没存值:用子图里那个节点自己的 widget 值

    def _resolve_output(self, node: _Node, slot: int, wanted: Any, visited: set) -> tuple | None:
        key = (node.id, "out", slot)
        if key in visited:
            return None  # 绕成了环(坏文件):当没接上
        visited.add(key)
        if node.mode == MODE_NEVER:
            return None
        if node.mode == MODE_BYPASS:
            index = self._bypass_input(node, slot, wanted)
            # 前端在这里不带类型往上找:按旁路节点那个输入自己的类型
            return None if index < 0 else self._resolve_input(node, node.inputs[index], visited)
        if node.type in self.definitions:
            return self._from_subgraph_output(node, slot, wanted, visited)
        if self._frontend_only(node):
            return self._through_frontend_node(node, slot, wanted, visited)
        return ("link", node.id, slot)

    def _from_subgraph_output(self, node: _Node, slot: int, wanted: Any, visited: set) -> tuple | None:
        child = self._child(node)
        for origin, origin_slot, target, target_slot, _ in child.links.values():
            if _same(target, child.output_node) and target_slot == slot:
                if _same(origin, child.input_node):
                    return self._from_subgraph_input(node, origin_slot, visited)
                inner = child.nodes.get(str(origin))
                return None if inner is None else self._resolve_output(_Node(child, inner), origin_slot, wanted, visited)
        return None

    def _through_frontend_node(self, node: _Node, slot: int, wanted: Any, visited: set) -> tuple | None:
        if node.type == _PRIMITIVE:
            # PrimitiveNode 在提交前把自己的值写进下游那一格(applyToGraph);第二格是它的「生成后怎样」
            stored = node.raw.get("widgets_values")
            if not isinstance(stored, list) or not stored or stored[0] is None:
                return None
            control = stored[1] if len(stored) > 1 and isinstance(stored[1], str) else ""
            return ("value", stored[0], control)
        source: _Node | None = node
        if node.type == _GET:
            source = self._set_node(node)
        if source is None:
            return None
        if source.type in _REROUTES or source.type == _SET:
            entries = source.inputs
            return self._resolve_input(source, entries[0], visited, wanted) if entries else None
        return None  # 别的前端节点(注释、rgthree 的开关)没有能往下流的东西

    @staticmethod
    def _set_node(node: _Node) -> _Node | None:
        """KJNodes 的 GetNode:同一层里标着同一个名字的 SetNode。"""
        stored = node.raw.get("widgets_values")
        name = stored[0] if isinstance(stored, list) and stored else None
        if not name:
            return None
        for raw in node.scope.nodes.values():
            values = raw.get("widgets_values")
            if raw.get("type") == _SET and isinstance(values, list) and values and values[0] == name:
                return _Node(node.scope, raw)
        return None

    @staticmethod
    def _bypass_input(node: _Node, slot: int, wanted: Any) -> int:
        """旁路节点的第 `slot` 个输出直通到哪个输入(ExecutableNodeDTO._getBypassSlotIndex)。"""
        inputs, outputs = node.inputs, node.outputs
        if not inputs:
            return -1
        if wanted in ("*", "", None):
            return slot if len(inputs) > slot else 0
        output_type = outputs[slot].get("type") if slot < len(outputs) else None
        if slot < len(inputs):
            opposite = inputs[slot].get("type")
            if _valid_connection(opposite, output_type) and _valid_connection(opposite, wanted):
                return slot
        for index, entry in enumerate(inputs):
            if entry.get("type") == wanted:
                return index
        for index, entry in enumerate(inputs):
            if _valid_connection(entry.get("type"), output_type) and _valid_connection(entry.get("type"), wanted):
                return index
        return -1
