"""ComfyUI 的图:UI 格式 → API 格式、看出一张图能调什么、把 Mosael 的请求填进去、收产出。

**所有「ComfyUI 内部格式」的知识只在这一个文件里。** 这些知识跟着 ComfyUI 的版本变(widget 的排法、
新的采样器节点、新的视频输出节点),所以它们住在插件里跟着插件走,而不是住在应用内核里跟着应用
发版(ADR 0020)。

ComfyUI 保存的工作流是 UI 图(nodes / links / widgets_values),而 `/prompt` 只吃 API 格式
(节点 id → {class_type, inputs})。两者的转换在 ComfyUI 前端的 graphToPrompt 里,没有后端接口 ——
这里复现它的核心语义。转换是**尽力而为**:认不出的非常规工作流,用户可以在 ComfyUI 里
「导出 (API)」,粘进这个连接的「API 模板」。
"""

from __future__ import annotations

import copy
import re
from typing import Any

# ---------------------------------------------------------------------------
# UI 图 → API 图
# ---------------------------------------------------------------------------

#: 纯 UI / 不进 API prompt 的节点(注释、分组标记、透传)。Reroute 在连线里单独透传。
_SKIP_NODE_TYPES = frozenset(
    {"Note", "MarkdownNote", "Reroute", "PrimitiveNode", "PrimitiveString", "PrimitiveInt", "PrimitiveFloat",
     "GetNode", "SetNode"}
)
#: ComfyUI 节点 mode:2 = muted、4 = bypassed —— 都不该进 prompt。
_INACTIVE_MODES = frozenset({2, 4})


def _has_control_after_generate(input_def: Any) -> bool:
    """object_info 里某个输入带 control_after_generate(seed 那一类 INT)——它在 widgets_values 里
    多占一个隐藏项(randomize / fixed / …),转换时必须跳过,否则后面的 widget 全部错位。"""
    return (
        isinstance(input_def, list)
        and len(input_def) > 1
        and isinstance(input_def[1], dict)
        and bool(input_def[1].get("control_after_generate"))
    )


def is_api_graph(graph: Any) -> bool:
    """已经是 API 格式了吗(「导出 (API)」出来的那种:节点 id → {class_type, inputs})。"""
    return (
        isinstance(graph, dict)
        and bool(graph)
        and "nodes" not in graph
        and all(isinstance(node, dict) and "class_type" in node for node in graph.values())
    )


def _input_defs(object_info: dict[str, Any], class_type: str) -> dict[str, Any]:
    type_input = (object_info.get(class_type) or {}).get("input") or {}
    return {**(type_input.get("required") or {}), **(type_input.get("optional") or {})}


def graph_to_api_prompt(ui_graph: dict[str, Any], object_info: dict[str, Any]) -> dict[str, Any]:
    """ComfyUI UI 图 → `/prompt` 的 API 格式。

    - 连接输入(node.inputs 里带 link)→ [源节点 id, 源槽位];Reroute 透传到真实的源。
    - widget 输入(带 widget 标记)→ 按顺序取 widgets_values,按 object_info 跳过隐藏的那一项。
    - 跳过 UI 专用节点和 muted / bypassed 的节点。
    """
    if is_api_graph(ui_graph):
        return copy.deepcopy(ui_graph)
    nodes = [node for node in (ui_graph.get("nodes") or []) if isinstance(node, dict)]
    links_by_id: dict[Any, list] = {}
    for link in ui_graph.get("links") or []:
        if isinstance(link, list) and len(link) >= 5:
            links_by_id[link[0]] = link
    nodes_by_id = {node.get("id"): node for node in nodes}

    def resolve_source(link_id: Any) -> list | None:
        """顺连线找到真实的源(节点 id, 槽位),透传 Reroute;防环。"""
        seen: set[Any] = set()
        while link_id is not None and link_id not in seen:
            seen.add(link_id)
            link = links_by_id.get(link_id)
            if not link:
                return None
            from_node, from_slot = link[1], link[2]
            source = nodes_by_id.get(from_node)
            if source is not None and source.get("type") == "Reroute":
                first_input = (source.get("inputs") or [{}])[0]
                link_id = first_input.get("link")
                continue
            return [str(from_node), from_slot]
        return None

    api: dict[str, Any] = {}
    for node in nodes:
        node_id, node_type = node.get("id"), node.get("type")
        if node_id is None or not node_type:
            continue
        if node.get("mode") in _INACTIVE_MODES or node_type in _SKIP_NODE_TYPES:
            continue
        input_defs = _input_defs(object_info, node_type)
        widgets = node.get("widgets_values")
        widgets = widgets if isinstance(widgets, list) else []
        inputs: dict[str, Any] = {}
        value_index = 0
        for entry in node.get("inputs") or []:
            name = entry.get("name")
            if not name:
                continue
            has_widget = "widget" in entry
            if entry.get("link") is not None:
                source = resolve_source(entry["link"])
                if source is not None:
                    inputs[name] = source
                # 转成输入的 widget 仍在 widgets_values 里占位置 —— 照样步进,否则后面的全对错。
                if has_widget and value_index < len(widgets):
                    value_index += 1
                    if _has_control_after_generate(input_defs.get(name)):
                        value_index += 1
            elif has_widget and value_index < len(widgets):
                inputs[name] = widgets[value_index]
                value_index += 1
                if _has_control_after_generate(input_defs.get(name)):
                    value_index += 1
        api[str(node_id)] = {"class_type": node_type, "inputs": inputs}
    return api


def ui_titles(ui_graph: dict[str, Any]) -> dict[str, str]:
    """节点 id → 界面上的名字(用户起的标题,或节点类型)。API 图里没有标题,只能从 UI 图拿。"""
    titles: dict[str, str] = {}
    if is_api_graph(ui_graph):
        for node_id, node in ui_graph.items():
            meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
            titles[str(node_id)] = str(meta.get("title") or node.get("class_type") or "")
        return titles
    for node in ui_graph.get("nodes") or []:
        if isinstance(node, dict):
            titles[str(node.get("id"))] = str(
                node.get("title") or (node.get("properties") or {}).get("Node name for S&R") or node.get("type") or ""
            )
    return titles


# ---------------------------------------------------------------------------
# 看出一张图的「角色」:提示词写哪儿、种子在哪、尺寸在哪、参考图接在哪
# ---------------------------------------------------------------------------

#: 从这些节点的 positive / negative(以及引导器的 conditioning)追溯到写提示词的那个节点。
_SAMPLER_TYPES = frozenset({"KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced"})
_GUIDER_MARK = "Guider"  # CFGGuider / BasicGuider / DualCFGGuider … Flux 那一路的提示词从这里进去
#: 写提示词的节点上,文字放在哪几个输入里。CLIPTextEncodeFlux 分成 clip_l / t5xxl 两格,SDXL 的
#: CLIPTextEncodeSDXL 分成 text_g / text_l —— 同一句话写进每一格。
_TEXT_INPUTS = ("text", "clip_l", "t5xxl", "text_g", "text_l")
#: 这些节点**生成画布**:宽高写在它们身上就是成片的尺寸。
_SIZE_NODE_TYPES = frozenset(
    {"WanImageToVideo", "WanFirstLastFrameToVideo", "WanVaceToVideo", "HunyuanImageToVideo", "LTXVImgToVideo",
     "CosmosImageToVideoLatent", "Wan22ImageToVideoLatent"}
)
#: 这些输入名说明参考图是**首帧**(视频从它开始动)/**尾帧**。
_FIRST_FRAME_INPUTS = frozenset({"start_image", "first_frame", "init_image"})
_LAST_FRAME_INPUTS = frozenset({"end_image", "last_frame"})
#: 输出节点 → 这张图产出什么。
_VIDEO_OUTPUT_TYPES = frozenset({"VHS_VideoCombine", "SaveVideo", "SaveWEBM", "CreateVideo", "SaveAnimatedWEBP",
                                 "SaveAnimatedPNG"})
_AUDIO_OUTPUT_TYPES = frozenset({"SaveAudio", "SaveAudioMP3", "SaveAudioOpus"})
_SAVE_NODE_TYPES = _VIDEO_OUTPUT_TYPES | _AUDIO_OUTPUT_TYPES | {"SaveImage", "PreviewImage"}


def _literal(value: Any) -> bool:
    """字面量输入(可以改),不是连线(`[节点 id, 槽位]`)。"""
    return not isinstance(value, list)


def _trace_text_node(api: dict[str, Any], ref: Any, prefer: str, seen: set[str]) -> str | None:
    """从 [节点, 槽位] 往上游追到写提示词的节点,穿过 ControlNetApply、FluxGuidance 这类条件处理节点。"""
    if not isinstance(ref, list) or not ref:
        return None
    node_id = str(ref[0])
    if node_id in seen:
        return None
    seen.add(node_id)
    node = api.get(node_id)
    if not isinstance(node, dict):
        return None
    inputs = node.get("inputs") or {}
    if any(key in inputs and _literal(inputs[key]) and isinstance(inputs[key], str) for key in _TEXT_INPUTS):
        return node_id
    for key in (prefer, "conditioning", "positive", "negative"):  # 优先同名槽,正负不混
        found = _trace_text_node(api, inputs.get(key), prefer, seen)
        if found is not None:
            return found
    return None


def text_roles(api: dict[str, Any]) -> dict[str, str]:
    """写提示词的节点 → "prompt" / "negative"。从采样器和引导器往上游追。"""
    roles: dict[str, str] = {}
    for node in api.values():
        class_type = str(node.get("class_type", ""))
        inputs = node.get("inputs") or {}
        if class_type in _SAMPLER_TYPES or _GUIDER_MARK in class_type:
            for slot, role in (("positive", "prompt"), ("conditioning", "prompt"), ("negative", "negative")):
                target = _trace_text_node(api, inputs.get(slot), slot, set())
                if target is not None:
                    roles.setdefault(target, role)
    return roles


def seed_inputs(api: dict[str, Any]) -> list[tuple[str, str]]:
    """所有字面量的种子:采样器的 seed、RandomNoise 的 noise_seed…… 一个种子该写进每一处。"""
    found: list[tuple[str, str]] = []
    for node_id, node in api.items():
        for name in ("seed", "noise_seed"):
            value = (node.get("inputs") or {}).get(name)
            if name in (node.get("inputs") or {}) and _literal(value) and not isinstance(value, str):
                found.append((node_id, name))
    return found


def size_node(api: dict[str, Any]) -> str | None:
    """决定成片宽高的那个节点(第一个生成画布的节点)。没有就是 None —— 那张图不收尺寸。"""
    for node_id in sorted(api, key=_node_order):
        node = api[node_id]
        class_type = str(node.get("class_type", ""))
        inputs = node.get("inputs") or {}
        sized = all(key in inputs and _literal(inputs[key]) for key in ("width", "height"))
        if sized and (class_type.startswith("Empty") or class_type in _SIZE_NODE_TYPES):
            return node_id
    return None


def _node_order(node_id: str) -> tuple[int, str]:
    """按数字排节点 id("10" 在 "9" 后面);子图里的 "12:5" 这种按前面的数字排。"""
    head = re.match(r"\d+", node_id)
    return (int(head.group()) if head else 1 << 30, node_id)


def kind_of(api: dict[str, Any]) -> str:
    """这张图产出什么:有视频输出节点就是 video,有音频输出节点就是 audio,否则 image。"""
    types = {str(node.get("class_type", "")) for node in api.values()}
    if types & _VIDEO_OUTPUT_TYPES:
        return "video"
    if types & _AUDIO_OUTPUT_TYPES:
        return "audio"
    return "image"


def image_slots(api: dict[str, Any], kind: str) -> list[dict[str, str]]:
    """LoadImage 节点 → 输入槽位 `{node, role}`,按节点顺序。

    角色看它**接到哪儿**:视频图里接到 start_image 这类输入的是首帧,接到 end_image 的是尾帧,
    其余都是参考图。图像图没有首尾帧这回事,一律是参考图。
    """
    consumers: dict[str, list[tuple[str, str]]] = {}
    for node in api.values():
        class_type = str(node.get("class_type", ""))
        for name, value in (node.get("inputs") or {}).items():
            if isinstance(value, list) and value:
                consumers.setdefault(str(value[0]), []).append((class_type, name))
    slots: list[dict[str, str]] = []
    for node_id in sorted(api, key=_node_order):
        node = api[node_id]
        if node.get("class_type") != "LoadImage":
            continue
        role = "reference_image"
        if kind == "video":
            for class_type, name in consumers.get(node_id, []):
                if name in _FIRST_FRAME_INPUTS or (name == "image" and "ImageToVideo" in class_type):
                    role = "first_frame"
                    break
                if name in _LAST_FRAME_INPUTS:
                    role = "last_frame"
                    break
        slots.append({"node": node_id, "role": role})
    return slots


# ---------------------------------------------------------------------------
# 描述:一张图 → 插件目录里的一个模型
# ---------------------------------------------------------------------------

#: 占位符(粘贴的 API 模板里用的写法)→ 它在请求里是什么。
PLACEHOLDERS = ("prompt", "negative", "seed", "width", "height", "steps", "duration_seconds")
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

#: 尺寸下拉里常备的几档。**这张图自己的尺寸**总在里面,且是默认值。
COMMON_SIZES = ("512x512", "768x768", "1024x1024", "832x1216", "1216x832", "1280x720", "720x1280", "1920x1080")


def _placeholders_in(graph: Any) -> set[str]:
    found: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
        elif isinstance(value, str):
            found.update(_PLACEHOLDER.findall(value))

    walk(graph)
    return found


def _schema(input_def: Any, value: Any) -> dict[str, Any] | None:
    """一个字面量输入 → JSON Schema 片段(类型 + 约束 + 当前值当默认)。认不出的类型回 None(不暴露)。"""
    if not isinstance(input_def, list) or not input_def:
        return None
    type_spec = input_def[0]
    constraints = input_def[1] if len(input_def) > 1 and isinstance(input_def[1], dict) else {}
    spec: dict[str, Any]
    if isinstance(type_spec, list):
        options = [one for one in type_spec if isinstance(one, (str, int, float))]
        if not options:
            return None
        spec = {"type": "string", "enum": [str(one) for one in options]}
    elif type_spec == "COMBO":
        options = constraints.get("options")
        if not isinstance(options, list) or not options:
            return None
        spec = {"type": "string", "enum": [str(one) for one in options]}
    elif type_spec in ("INT", "FLOAT"):
        spec = {"type": "integer" if type_spec == "INT" else "number"}
        for source, target in (("min", "minimum"), ("max", "maximum"), ("step", "multipleOf")):
            bound = constraints.get(source)
            if isinstance(bound, (int, float)) and not isinstance(bound, bool):
                spec[target] = bound
        if type_spec == "INT":
            spec.pop("multipleOf", None)
    elif type_spec == "BOOLEAN":
        spec = {"type": "boolean"}
    elif type_spec == "STRING":
        spec = {"type": "string"}
        if constraints.get("multiline"):
            spec["x-multiline"] = True
    else:
        return None
    if isinstance(value, (str, int, float, bool)):
        spec["default"] = value
    return spec


def describe(
    model_id: str,
    label: Any,
    api: dict[str, Any],
    object_info: dict[str, Any],
    titles: dict[str, str] | None = None,
) -> dict[str, Any]:
    """一张 API 图 → 插件目录里的一个模型(见 docs/PLUGIN_MANIFEST 的「替宿主做生成」)。

    - 提示词 / 反向提示词、种子、尺寸对到宿主自己的控件上(`negative_prompt` / `seed` / `size`);
    - 其余可调的字面量输入按 `<节点 id>.<输入名>` 列成参数,带着 ComfyUI 自己给的类型、范围和可选值;
    - LoadImage 节点列成输入槽位;
    - 粘贴的模板里的 `{{占位符}}` 一样认。
    """
    titles = titles or {}
    kind = kind_of(api)
    roles = text_roles(api)
    seeds = set(seed_inputs(api))
    sized = size_node(api)
    placeholders = _placeholders_in(api)
    slots = image_slots(api, kind)
    slot_nodes = {slot["node"] for slot in slots}

    parameters: dict[str, dict[str, Any]] = {}
    if "negative" in roles.values() or "negative" in placeholders:
        parameters["negative_prompt"] = {"type": "string"}
    if seeds or "seed" in placeholders:
        parameters["seed"] = {"type": "integer", "minimum": 0}
    if sized is not None or {"width", "height"} & placeholders:
        size: dict[str, Any] = {"type": "string"}
        own = ""
        if sized is not None:
            inputs = api[sized]["inputs"]
            if isinstance(inputs.get("width"), int) and isinstance(inputs.get("height"), int):
                own = f"{inputs['width']}x{inputs['height']}"
        choices = ([own] if own else []) + [one for one in COMMON_SIZES if one != own]
        size["enum"] = choices
        if own:
            size["default"] = own
        parameters["size"] = size
    if "steps" in placeholders:
        parameters["steps"] = {"type": "integer", "minimum": 1, "maximum": 200, "default": 20,
                               "title": {"zh": "步数", "en": "Steps"}}
    if "duration_seconds" in placeholders:
        parameters["duration_seconds"] = {"type": "integer", "minimum": 1}

    for node_id in sorted(api, key=_node_order):
        node = api[node_id]
        class_type = str(node.get("class_type", ""))
        defs = _input_defs(object_info, class_type)
        for name, value in (node.get("inputs") or {}).items():
            if not _literal(value):
                continue
            if isinstance(value, str) and _PLACEHOLDER.search(value):
                continue  # 占位符由宿主的主控件填,不再单独列
            if node_id in roles and name in _TEXT_INPUTS:
                continue  # 提示词 / 反向提示词
            if (node_id, name) in seeds:
                continue
            if node_id == sized and name in ("width", "height"):
                continue
            if node_id in slot_nodes and name in ("image", "upload"):
                continue  # 参考图槽位
            spec = _schema(defs.get(name), value)
            if spec is None:
                continue
            spec["title"] = f"{titles.get(node_id) or class_type} · {name}"
            if class_type in _SAVE_NODE_TYPES:
                spec["x-advanced"] = True
            parameters[f"{node_id}.{name}"] = spec

    counts: dict[str, int] = {}
    for slot in slots:
        counts[slot["role"]] = counts.get(slot["role"], 0) + 1
    inputs = [{"role": role, "max": count} for role, count in counts.items()]

    if kind == "video":
        if "first_frame" in counts and "last_frame" in counts:
            modes = ["keyframes-to-video"]
        elif "first_frame" in counts:
            modes = ["image-to-video"]
        else:
            modes = ["text-to-video"] + (["reference-to-video"] if "reference_image" in counts else [])
    else:
        modes = ["text-to-image"] + (["image-to-image"] if "reference_image" in counts else [])

    model: dict[str, Any] = {
        "id": model_id,
        "label": label,
        "kind": kind,
        "modes": modes,
        "parameters": parameters,
        "inputs": inputs,
    }
    types = {str(node.get("class_type", "")) for node in api.values()}
    # 提示词写法:SD 1.5 / SDXL 那一路(CheckpointLoaderSimple)吃逗号分隔的标签;Flux 这类走 UNETLoader
    # 的吃自然语言,不标。
    if "CheckpointLoaderSimple" in types and not {"UNETLoader", "DualCLIPLoader"} & types:
        model["prompt_dialect"] = "sd-tags"
    return model


# ---------------------------------------------------------------------------
# 填:把一次请求写进图里
# ---------------------------------------------------------------------------


def substitute_placeholders(graph: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
    """填 `{{key}}` 占位符。

    在**解析之后**填,不是对 JSON 文本做字符串替换:提示词里的引号、反斜杠永远破坏不了文档。
    一整格就是一个占位符的,填原值(`"{{seed}}"` 变成整数 —— KSampler 要的就是整数);
    夹在文字里的,按文字拼进去。没给值的占位符原样留着(下游看得到是哪一格没填)。
    """

    def fill(value: Any) -> Any:
        if isinstance(value, dict):
            return {key: fill(item) for key, item in value.items()}
        if isinstance(value, list):
            return [fill(item) for item in value]
        if isinstance(value, str):
            whole = _PLACEHOLDER.fullmatch(value)
            if whole and whole.group(1) in values:
                return values[whole.group(1)]
            return _PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), value)
        return value

    return fill(copy.deepcopy(graph))


def fill(api: dict[str, Any], values: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    """把一次请求写进 API 图(返回新图,不改入参)。

    `values`:提示词 / 反向 / 种子 / 宽高 —— 宿主的主控件。**只写给了的**:用户没选尺寸,这张图就用
    它自己的尺寸,而不是被一个默认的 1024 盖掉。
    `overrides`:`<节点 id>.<输入名>` → 值,用户在参数表里动过的那些。只改字面量输入;节点或输入
    已经不在了就跳过(工作流可能在 ComfyUI 里改过了,不该为此报错)。
    """
    graph = copy.deepcopy(api)
    roles = text_roles(graph)
    for node_id, role in roles.items():
        text = values.get(role)
        if text is None:
            continue
        inputs = graph[node_id]["inputs"]
        for name in _TEXT_INPUTS:
            if name in inputs and _literal(inputs[name]) and isinstance(inputs[name], str):
                inputs[name] = text
    if values.get("seed") is not None:
        for node_id, name in seed_inputs(graph):
            graph[node_id]["inputs"][name] = values["seed"]
    sized = size_node(graph)
    if sized is not None and values.get("width") and values.get("height"):
        graph[sized]["inputs"]["width"] = values["width"]
        graph[sized]["inputs"]["height"] = values["height"]
    for key, value in (overrides or {}).items():
        node_id, dot, name = str(key).partition(".")
        if not dot:
            continue
        node = graph.get(node_id)
        if isinstance(node, dict) and name in (node.get("inputs") or {}) and _literal(node["inputs"][name]):
            node["inputs"][name] = value
    return substitute_placeholders(graph, {key: value for key, value in values.items() if value is not None})


def wire_images(api: dict[str, Any], kind: str, uploaded: dict[str, list[str]]) -> dict[str, Any]:
    """把传上去的参考图接到 LoadImage 节点上:每个角色的第 i 张给这个角色的第 i 个槽位。

    给得比槽位少,剩下的槽位用它原来那张图;给得比槽位多,多的不接(宿主按槽位数限过了)。
    """
    graph = copy.deepcopy(api)
    used: dict[str, int] = {}
    for slot in image_slots(graph, kind):
        names = uploaded.get(slot["role"]) or []
        index = used.get(slot["role"], 0)
        if index < len(names):
            graph[slot["node"]]["inputs"]["image"] = names[index]
            used[slot["role"]] = index + 1
    return graph


# ---------------------------------------------------------------------------
# 收:跑完的图交出了什么
# ---------------------------------------------------------------------------

#: ComfyUI 输出节点把文件记在这几个键下面:SaveImage → images,VHS → gifs,新的视频节点 → videos。
OUTPUT_KEYS = ("images", "gifs", "videos", "audio")
_VIDEO_SUFFIXES = (".mp4", ".webm", ".mov", ".mkv", ".gif", ".webp")


def collect_outputs(history_entry: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """一张跑完的图交出的文件,按这次要的种类挑。

    存下来的(type=output)优先;一个都没有才用预览(type=temp)—— 只接了 PreviewImage 的图也能出东西。
    视频图里常常同时有逐帧的图和合成的视频:要的是视频那一份。
    """
    found: list[dict[str, Any]] = []
    for node_output in (history_entry.get("outputs") or {}).values():
        if not isinstance(node_output, dict):
            continue
        for key in OUTPUT_KEYS:
            for item in node_output.get(key) or []:
                if isinstance(item, dict) and item.get("filename"):
                    found.append(item)
    saved = [item for item in found if item.get("type") != "temp"] or found
    if kind == "video":
        videos = [item for item in saved if str(item["filename"]).lower().endswith(_VIDEO_SUFFIXES)]
        return videos[:1] or saved[:1]
    return saved


def execution_error(status: dict[str, Any]) -> str:
    """ComfyUI 自己说的失败原因;一句都没有就是空串。"""
    for message in reversed(status.get("messages") or []):
        if isinstance(message, list) and len(message) == 2 and message[0] == "execution_error":
            payload = message[1] or {}
            node = payload.get("node_type") or ""
            said = payload.get("exception_message") or ""
            return f"{node}: {said}".strip(": ") if said or node else "execution_error"
    return ""


def validation_errors(detail: dict[str, Any]) -> str:
    """`/prompt` 回 400 时的校验错误:顶层那句 + 每个节点的每一条。"""
    lines: list[str] = []
    top = detail.get("error")
    if isinstance(top, dict) and top.get("message"):
        lines.append(str(top["message"]))
    for node_id, node in (detail.get("node_errors") or {}).items():
        for problem in (node or {}).get("errors") or []:
            said = problem.get("message") if isinstance(problem, dict) else problem
            extra = problem.get("details") if isinstance(problem, dict) else ""
            lines.append(f"#{node_id} {said}{(': ' + str(extra)) if extra else ''}")
    return "; ".join(lines)
