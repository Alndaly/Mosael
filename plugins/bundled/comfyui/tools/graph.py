"""ComfyUI 的 API 图:看出一张图能调什么、把 Mosael 的请求填进去、收产出。

「ComfyUI 内部格式」的知识只在插件里(这个文件和 convert.py):它们跟着 ComfyUI 的版本变(新的采样器节点、
新的视频输出节点),所以住在插件里跟着插件走,而不是住在应用内核里跟着应用发版(ADR 0020)。
UI 图(保存的工作流)怎么变成这里吃的 API 图,见 convert.py。
"""

from __future__ import annotations

import copy
import random
import re
from typing import Any

import convert
import labels


def _input_defs(object_info: dict[str, Any], class_type: str) -> dict[str, Any]:
    type_input = (object_info.get(class_type) or {}).get("input") or {}
    return {**(type_input.get("required") or {}), **(type_input.get("optional") or {})}


# ---------------------------------------------------------------------------
# 看出一张图的「角色」:提示词写哪儿、种子在哪、尺寸在哪、输入素材接在哪、产出从哪出
# ---------------------------------------------------------------------------

#: 从这些节点的 positive / negative(以及引导器的 conditioning)追溯到写提示词的那个节点。
_SAMPLER_TYPES = frozenset({"KSampler", "KSamplerAdvanced", "SamplerCustom", "SamplerCustomAdvanced"})
_GUIDER_MARK = "Guider"  # CFGGuider / BasicGuider / DualCFGGuider … Flux 那一路的提示词从这里进去
#: 写提示词的节点上,文字放在哪几个输入里。CLIPTextEncodeFlux 分成 clip_l / t5xxl 两格,SDXL 的
#: CLIPTextEncodeSDXL 分成 text_g / text_l —— 同一句话写进每一格。
_TEXT_INPUTS = ("text", "clip_l", "t5xxl", "text_g", "text_l")
#: 后端的「一段文字」节点:提示词常常写在它身上,再连进 CLIPTextEncode 的 text(新版的模板就这么排)。
_STRING_SOURCES = frozenset({"PrimitiveString", "PrimitiveStringMultiline"})
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
_AUDIO_OUTPUT_TYPES = frozenset({"SaveAudio", "SaveAudioMP3", "SaveAudioOpus", "PreviewAudio"})
_IMAGE_OUTPUT_TYPES = frozenset({"SaveImage", "PreviewImage", "Image Save", "SaveImageWebsocket"})
#: 把文字显示出来的输出节点(描述图片、反推提示词这一类工作流的产出就是一段字)。
_TEXT_OUTPUT_TYPES = frozenset({"ShowText|pysssss", "PreviewAny", "PreviewText", "Display Any (rgthree)",
                                "ShowText", "easy showAnything"})
_SAVE_NODE_TYPES = _VIDEO_OUTPUT_TYPES | _AUDIO_OUTPUT_TYPES | _IMAGE_OUTPUT_TYPES

#: 读入一份素材的节点 → (它读的是什么, 文件名写在哪个输入里)。
#: LoadImage 读图;它的第二个输出是 alpha 通道当蒙版 —— 只接了那一路的,当蒙版槽位用。
_LOADERS: dict[str, tuple[str, str]] = {
    "LoadImage": ("image", "image"),
    "LoadImageMask": ("mask", "image"),
    "LoadVideo": ("video", "file"),
    "VHS_LoadVideo": ("video", "video"),
    "LoadAudio": ("audio", "audio"),
    "VHS_LoadAudioUpload": ("audio", "audio"),
}

#: 这些节点说明图里在做什么 —— 给 `list_workflows` 的 `features`,让智能体挑得出「能放大的那张」。
_FEATURE_MARKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("upscale", ("ImageUpscaleWithModel", "UpscaleModelLoader", "LatentUpscale", "ImageScaleBy", "UltimateSDUpscale")),
    ("inpaint", ("VAEEncodeForInpaint", "InpaintModelConditioning", "SetLatentNoiseMask", "Inpaint")),
    ("remove-background", ("RemBG", "Rembg", "BiRefNet", "RMBG", "BackgroundRemov", "InspyrenetRembg")),
    ("face-restore", ("FaceRestore", "ReActor", "FaceDetailer", "CodeFormer", "GFPGAN")),
    ("frame-interpolation", ("RIFE", "FILM VFI", "FILM_VFI", "Interpolat")),
    ("controlnet", ("ControlNetApply", "ControlNetLoader")),
    ("lora", ("LoraLoader",)),
)


def _literal(value: Any) -> bool:
    """字面量输入(可以改),不是连线(`[节点 id, 槽位]`)。"""
    return not isinstance(value, list)


def text_fields(node: dict[str, Any]) -> list[str]:
    """这个节点上存着提示词文字的那几格(字面量字符串)。"""
    inputs = node.get("inputs") or {}
    names = ("value",) if str(node.get("class_type", "")) in _STRING_SOURCES else _TEXT_INPUTS
    return [name for name in names if name in inputs and _literal(inputs[name]) and isinstance(inputs[name], str)]


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
    if text_fields(node):
        return node_id
    for key in _TEXT_INPUTS:
        # 文字从一个「一段文字」节点连进来:提示词写在那个节点上
        source = inputs.get(key)
        upstream = api.get(str(source[0])) if isinstance(source, list) and source else None
        if isinstance(upstream, dict) and str(upstream.get("class_type", "")) in _STRING_SOURCES and text_fields(upstream):
            return str(source[0])
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


def prompt_requirement(api: dict[str, Any], roles: dict[str, str] | None = None,
                       placeholders: set[str] | None = None) -> str:
    """这张图对提示词的要求(宿主描述符的 `prompt`,见 docs/PLUGIN_MANIFEST 的「替宿主做生成」):

    - `required`:模板里有 `{{prompt}}` 占位符(没有默认值,不填就是一句字面的占位符),或者喂给采样器的
      提示词节点里有一个存着的是空串 —— 不写的话那张图拿空话去跑;
    - `optional`:有喂给采样器的提示词节点,而且**每一个都存着一句话** —— 不写就用这张图自己那句,
      写了就换成你的;
    - `none`:没有任何文字喂进采样器(放大、抠图、修脸、补帧这类「处理一份素材」的图)。宿主不摆
      提示词框,也不逼人敲一句没用的话。

    判的是**喂进采样器 / 引导器的**文字(见 text_roles),不是图里有没有 CLIPTextEncode:一个没接上的
    文字节点什么都不影响。反向提示词不算 —— 它有自己的控件。
    """
    placeholders = _placeholders_in(api) if placeholders is None else placeholders
    if "prompt" in placeholders:
        return "required"
    roles = text_roles(api) if roles is None else roles
    positive = [node_id for node_id, role in roles.items() if role == "prompt"]
    if not positive:
        return "none"
    for node_id in positive:
        inputs = api[node_id].get("inputs") or {}
        saved = [inputs[name] for name in text_fields(api[node_id])]
        if not any(text.strip() for text in saved):
            return "required"
    return "optional"


def _changes_each_run(node: dict[str, Any], name: str) -> bool:
    meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
    controls = meta.get(convert.CONTROLS) if isinstance(meta.get(convert.CONTROLS), dict) else {}
    return controls.get(name, "fixed") != "fixed"


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


def batch_input(api: dict[str, Any]) -> str | None:
    """一次出几张写在哪:画布节点上的字面量 `batch_size`。没有就是 None(这张图一次只出它自己那么多)。"""
    sized = size_node(api)
    if sized is None:
        return None
    value = (api[sized].get("inputs") or {}).get("batch_size")
    return sized if isinstance(value, int) and not isinstance(value, bool) else None


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


def _consumers(api: dict[str, Any]) -> dict[str, list[tuple[str, str, int]]]:
    """节点 id → 谁在用它的输出:[(下游的类名, 下游的输入名, 用的是第几个输出)]。"""
    consumers: dict[str, list[tuple[str, str, int]]] = {}
    for node in api.values():
        class_type = str(node.get("class_type", ""))
        for name, value in (node.get("inputs") or {}).items():
            if isinstance(value, list) and len(value) >= 2:
                slot = value[1] if isinstance(value[1], int) else 0
                consumers.setdefault(str(value[0]), []).append((class_type, name, slot))
    return consumers


def slots(api: dict[str, Any], kind: str, titles: dict[str, str] | None = None) -> list[dict[str, str]]:
    """读素材的节点 → 输入槽位 `{node, class_type, title, media, field, role}`,按节点顺序。

    角色看它**接到哪儿**(宿主的素材角色,见 ai/providers/contracts/generation.SOURCE_ROLES):

    - 图:视频图里接到 start_image 这类输入的是首帧、接到 end_image 的是尾帧,其余是参考图;
      只用了 LoadImage 的第二个输出(alpha 当蒙版)的,是蒙版;
    - LoadImageMask:蒙版;
    - 视频(LoadVideo / VHS_LoadVideo):被改的那一段(源视频);
    - 音频:视频图里是驱动音频(口型、卡点),别的图里是参考音频。
    """
    titles = titles or {}
    consumers = _consumers(api)
    found: list[dict[str, str]] = []
    for node_id in sorted(api, key=_node_order):
        node = api[node_id]
        class_type = str(node.get("class_type", ""))
        loader = _LOADERS.get(class_type)
        if loader is None:
            continue
        media, field_name = loader
        used = consumers.get(node_id, [])
        role = "reference_image"
        if media == "image":
            outputs_used = {slot for _, _, slot in used}
            if outputs_used == {1}:
                media, role = "mask", "mask"
            elif kind == "video":
                for class_name, name, slot in used:
                    if slot != 0:
                        continue
                    if name in _FIRST_FRAME_INPUTS or (name == "image" and "ImageToVideo" in class_name):
                        role = "first_frame"
                        break
                    if name in _LAST_FRAME_INPUTS:
                        role = "last_frame"
                        break
        elif media == "mask":
            role = "mask"
        elif media == "video":
            role = "source_video"
        elif media == "audio":
            role = "driving_audio" if kind == "video" else "reference_audio"
        found.append({
            "node": node_id,
            "class_type": class_type,
            "title": titles.get(node_id) or class_type,
            "media": media,
            "field": field_name,
            "role": role,
        })
    return found


def features(api: dict[str, Any], found_slots: list[dict[str, str]] | None = None) -> list[str]:
    """这张图在做什么(给人和智能体挑工作流用):upscale / inpaint / img2img / remove-background / …"""
    types = [str(node.get("class_type", "")) for node in api.values()]
    tags: list[str] = []
    for tag, marks in _FEATURE_MARKS:
        if any(mark in class_type for class_type in types for mark in marks):
            tags.append(tag)
    found_slots = found_slots if found_slots is not None else slots(api, kind_of(api))
    if any(slot["role"] == "mask" for slot in found_slots) and "inpaint" not in tags:
        tags.append("inpaint")
    if "VAEEncode" in types and any(slot["media"] == "image" for slot in found_slots):
        tags.append("img2img")
    if text_roles(api):
        tags.append("prompt")
    return tags


def output_nodes(api: dict[str, Any], object_info: dict[str, Any] | None = None,
                 titles: dict[str, str] | None = None) -> list[dict[str, str]]:
    """会交出东西的节点 `{node, class_type, title, media}`。

    ComfyUI 在 object_info 里给每个输出节点标了 `output_node: true` —— 有它就信它(自定义节点也认得出),
    再按已知的几类说它交出的是图、视频、音频还是一段字。
    """
    titles = titles or {}
    object_info = object_info or {}
    found: list[dict[str, str]] = []
    for node_id in sorted(api, key=_node_order):
        class_type = str(api[node_id].get("class_type", ""))
        if class_type not in _KNOWN_OUTPUT_TYPES and not (object_info.get(class_type) or {}).get("output_node"):
            continue
        found.append({"node": node_id, "class_type": class_type, "title": titles.get(node_id) or class_type,
                      "media": output_media(class_type)})
    return found


_KNOWN_OUTPUT_TYPES = _VIDEO_OUTPUT_TYPES | _AUDIO_OUTPUT_TYPES | _IMAGE_OUTPUT_TYPES | _TEXT_OUTPUT_TYPES


def media_outputs(api: dict[str, Any], object_info: dict[str, Any] | None = None,
                  titles: dict[str, str] | None = None) -> list[dict[str, str]]:
    """会交出**文件**的输出节点:图、视频、音频,以及认不出种类的自定义输出节点(多半是某种保存节点)。

    只交出一段字的(反推提示词、打标签)不算 —— 这种图**不是生成模型**:生成是「一段提示词 → 一份成片」,
    它交不出成片,`kind_of` 却会把它兜成 image,选了它的生成永远拿不回一张图。它照样是一个工具(见 tooling)。
    """
    return [node for node in output_nodes(api, object_info, titles) if node["media"] != "text"]


def output_media(class_type: str) -> str:
    """一个输出节点交出的是什么:认得的几类说 image / video / audio / text,别的(自定义的输出节点)是 any。

    声明输出(output_nodes)和交回产出(按节点记具名输出)用的是同一个判据 —— 两边各判各的,
    一个自定义保存节点声明的是 `output_12`,交回时却记在按文件后缀起名的 `image_12` 上。
    """
    if class_type in _VIDEO_OUTPUT_TYPES:
        return "video"
    if class_type in _AUDIO_OUTPUT_TYPES:
        return "audio"
    if class_type in _IMAGE_OUTPUT_TYPES:
        return "image"
    if class_type in _TEXT_OUTPUT_TYPES:
        return "text"
    return "any"


# ---------------------------------------------------------------------------
# 描述:一张图 → 插件目录里的一个模型
# ---------------------------------------------------------------------------

#: 占位符(粘贴的 API 模板里用的写法)→ 它在请求里是什么。
PLACEHOLDERS = ("prompt", "negative", "seed", "width", "height", "steps", "duration_seconds")
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")

#: 尺寸下拉里常备的几档。**这张图自己的尺寸**总在里面,且是默认值。
COMMON_SIZES = ("512x512", "768x768", "1024x1024", "832x1216", "1216x832", "1280x720", "720x1280", "1920x1080")
#: 一次最多出几张(宿主一次生成的上限,见 ai/providers/contracts/generation.MAX_NUM_IMAGES)。
MAX_BATCH = 4


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


def tunable(
    api: dict[str, Any],
    object_info: dict[str, Any],
    titles: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """这张图里**给人调的**那些字面量输入:`<节点 id>.<输入名>` → JSON Schema 片段,按常用程度排好。

    宿主自己有控件的(提示词、种子、尺寸、一次几张)、读素材的槽位、不该在 Mosael 里调的(文件名前缀)
    都不在这里。名字是人话(见 labels),原始的「节点 · 输入名」在 description 里。
    """
    titles = titles or {}
    roles = text_roles(api)
    seeds = set(seed_inputs(api))
    sized = size_node(api)
    slot_fields = {(slot["node"], slot["field"]) for slot in slots(api, kind_of(api))}
    found: list[tuple[labels.Parameter, dict[str, Any]]] = []
    order = 0
    for node_id in sorted(api, key=_node_order):
        node = api[node_id]
        class_type = str(node.get("class_type", ""))
        defs = _input_defs(object_info, class_type)
        for name, value in (node.get("inputs") or {}).items():
            order += 1
            if not isinstance(value, (str, int, float, bool)) or name in labels.HIDDEN_INPUTS:
                # 连线,以及包成 {"__value__": …} 的数组值(参数表只有标量控件)
                continue
            if isinstance(value, str) and _PLACEHOLDER.search(value):
                continue  # 占位符由宿主的主控件填,不再单独列
            if node_id in roles and name in text_fields(node):
                continue  # 提示词 / 反向提示词
            if (node_id, name) in seeds:
                continue
            if node_id == sized and name in ("width", "height", "batch_size"):
                continue  # 尺寸与一次几张:宿主的控件
            if (node_id, name) in slot_fields or class_type in _LOADERS and name in ("image", "upload", "channel"):
                continue  # 读素材的槽位
            spec = _schema(defs.get(name), value)
            if spec is None:
                continue
            described = labels.describe(node_id, name, class_type, titles.get(node_id, ""), order)
            if not described.common or class_type in _SAVE_NODE_TYPES:
                spec["x-advanced"] = True
            spec["description"] = f"{titles.get(node_id) or class_type} · {name}"
            found.append((described, spec))
    found.sort(key=lambda pair: pair[0].rank)
    names = labels.titled([described for described, _ in found])
    return {described.key: {"title": names[described.key], **spec} for described, spec in found}


def describe(
    model_id: str,
    label: Any,
    api: dict[str, Any],
    object_info: dict[str, Any],
    titles: dict[str, str] | None = None,
) -> dict[str, Any]:
    """一张 API 图 → 插件目录里的一个模型(见 docs/PLUGIN_MANIFEST 的「替宿主做生成」)。

    - 提示词 / 反向提示词、种子、尺寸、一次几张对到宿主自己的控件上(`negative_prompt` / `seed` / `size` /
      `num_images`);
    - 其余可调的字面量输入按 `<节点 id>.<输入名>` 列成参数(见 `tunable`);
    - 读素材的节点列成输入槽位(图、蒙版、首尾帧、视频、音频);
    - 粘贴的模板里的 `{{占位符}}` 一样认;
    - 提示词要不要写(`prompt`)从图里读:没有文字喂进采样器的(放大、抠图)是 `none`(见 prompt_requirement)。
    """
    titles = titles or {}
    kind = kind_of(api)
    roles = text_roles(api)
    seeds = set(seed_inputs(api))
    sized = size_node(api)
    placeholders = _placeholders_in(api)
    found_slots = slots(api, kind, titles)

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
    batched = batch_input(api)
    max_outputs = 1
    if kind == "image" and batched is not None:
        own_batch = int(api[batched]["inputs"]["batch_size"])
        max_outputs = MAX_BATCH
        parameters["num_images"] = {"type": "integer", "minimum": 1, "maximum": MAX_BATCH,
                                    "default": max(1, min(own_batch, MAX_BATCH))}
    if "steps" in placeholders:
        parameters["steps"] = {"type": "integer", "minimum": 1, "maximum": 200, "default": 20,
                               "title": {"zh": "步数", "en": "Steps"}}
    if "duration_seconds" in placeholders:
        parameters["duration_seconds"] = {"type": "integer", "minimum": 1}
    parameters.update(tunable(api, object_info, titles))

    counts: dict[str, int] = {}
    for slot in found_slots:
        counts[slot["role"]] = counts.get(slot["role"], 0) + 1
    prompted = bool(roles) or "prompt" in placeholders
    image_roles = ("reference_image", "first_frame", "last_frame")
    # 没有提示词、也没有自己的画布(放大、抠图、修脸这类「处理一张图」的工作流):那张图是必须给的 ——
    # 否则 ComfyUI 会拿工作流里存着的那张示例图跑一遍,用户拿回来的不是自己的图。
    needs_image = not prompted or (sized is None and kind == "image")
    inputs: list[dict[str, Any]] = []
    first_image_marked = False
    for role, count in counts.items():
        entry: dict[str, Any] = {"role": role, "max": count}
        if needs_image and role in image_roles and not first_image_marked:
            entry["required"] = True
            first_image_marked = True
        if role in ("mask", "source_video"):
            entry["required"] = True
        inputs.append(entry)

    if kind == "video":
        if "source_video" in counts:
            modes = ["video-edit"]
        elif "first_frame" in counts and "last_frame" in counts:
            modes = ["keyframes-to-video"]
        elif "first_frame" in counts:
            modes = ["image-to-video"]
        else:
            modes = ["text-to-video"] + (["reference-to-video"] if "reference_image" in counts else [])
    elif kind == "audio":
        # 音乐 / 音效 / 配音(ADR 0022):宿主的音频模式里通用的那一个
        modes = ["text-to-audio"]
    else:
        has_image = any(role in counts for role in image_roles) or "mask" in counts
        modes = (["text-to-image"] if prompted and not needs_image else []) + (["image-to-image"] if has_image else [])
        modes = modes or ["text-to-image"]

    model: dict[str, Any] = {
        "id": model_id,
        "label": label,
        "kind": kind,
        "modes": modes,
        "parameters": parameters,
        "inputs": inputs,
        "max_outputs": max_outputs,
        # 提示词要不要写:从图里读(见 prompt_requirement)。放大这类图是 none —— 宿主不再逼人敲一句没用的话。
        "prompt": prompt_requirement(api, roles, placeholders),
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

    `values`:提示词 / 反向 / 种子 / 宽高 / 一次几张(`batch`)—— 宿主的主控件。**只写给了的**:用户没选尺寸,
    这张图就用它自己的尺寸,而不是被一个默认的 1024 盖掉。
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
        for name in text_fields(graph[node_id]):
            inputs[name] = text
    for node_id, name in seed_inputs(graph):
        if values.get("seed") is not None:
            graph[node_id]["inputs"][name] = values["seed"]
        elif _changes_each_run(graph[node_id], name):
            # 没给种子:照工作流自己的设定 —— 界面上每次生成都换种子的(randomize / increment …),通过 API 跑
            # 也得换,否则同一张图跑两遍拿回同一张图(ComfyUI 还会整张命中缓存);固定的(fixed)留着存的那个
            graph[node_id]["inputs"][name] = random.randint(0, 2**31 - 1)
    sized = size_node(graph)
    if sized is not None and values.get("width") and values.get("height"):
        graph[sized]["inputs"]["width"] = values["width"]
        graph[sized]["inputs"]["height"] = values["height"]
    batched = batch_input(graph)
    if batched is not None and isinstance(values.get("batch"), int) and values["batch"] >= 1:
        graph[batched]["inputs"]["batch_size"] = min(int(values["batch"]), MAX_BATCH)
    for key, value in (overrides or {}).items():
        node_id, dot, name = str(key).partition(".")
        if not dot:
            continue
        node = graph.get(node_id)
        if isinstance(node, dict) and name in (node.get("inputs") or {}) and _literal(node["inputs"][name]):
            node["inputs"][name] = value
    return substitute_placeholders(graph, {key: value for key, value in values.items() if value is not None})


def wire_inputs(api: dict[str, Any], kind: str, uploaded: dict[str, list[str]]) -> dict[str, Any]:
    """把传上去的素材接到读素材的节点上:每个角色的第 i 份给这个角色的第 i 个槽位。

    给得比槽位少,剩下的槽位用它原来那份;给得比槽位多,多的不接(宿主按槽位数限过了)。

    **蒙版没有自己的槽位**时(局部重绘图常见的做法:LoadImage 的 alpha 就是蒙版,用户在 ComfyUI 的
    蒙版编辑器里画),给的蒙版另起一个 LoadImageMask,把原来接在 alpha 那一路上的下游改接过去 ——
    否则单独给的蒙版无处可去,重绘的还是工作流里存着的那一块。
    """
    graph = copy.deepcopy(api)
    used: dict[str, int] = {}
    found = slots(graph, kind)
    for slot in found:
        names = uploaded.get(slot["role"]) or []
        index = used.get(slot["role"], 0)
        if index < len(names):
            put_input(graph, slot["node"], names[index])
            used[slot["role"]] = index + 1
    masks = uploaded.get("mask") or []
    if masks and not any(slot["role"] == "mask" for slot in found):
        mask_sources = {slot["node"] for slot in found if slot["class_type"] == "LoadImage" and slot["media"] == "image"}
        rewired = False
        new_id = str(max((_node_order(one)[0] for one in graph if _node_order(one)[0] < 1 << 30), default=0) + 1)
        for node in graph.values():
            for name, value in (node.get("inputs") or {}).items():
                if isinstance(value, list) and len(value) >= 2 and str(value[0]) in mask_sources and value[1] == 1:
                    node["inputs"][name] = [new_id, 0]
                    rewired = True
        if rewired:
            graph[new_id] = {"class_type": "LoadImageMask", "inputs": {"image": masks[0], "channel": _MASK_CHANNEL},
                             "_meta": {"title": "Mosael mask"}}
    return graph


#: 宿主的蒙版是「白色是要改的地方」的黑白图(见 ai/providers/contracts/generation.MASK),没有透明通道 ——
#: 读它的红色通道。照 alpha 读的话一张不透明的图读出来是全空的蒙版,什么都不重绘。
_MASK_CHANNEL = "red"


def put_input(api: dict[str, Any], node_id: str, name: str) -> dict[str, Any]:
    """把传上去的一份素材(ComfyUI input 目录里的名字)接到读素材的节点 `node_id` 上。就地改,也交回这张图。

    蒙版按宿主的规矩读(白色是要改的地方):LoadImageMask 改读红色通道;只用了 alpha 那一路的 LoadImage
    (蒙版槽位)就地换成读红色通道的 LoadImageMask,下游改接它唯一的那个输出。
    """
    node = api[node_id]
    class_type = str(node.get("class_type", ""))
    inputs = node.setdefault("inputs", {})
    field_name = _LOADERS[class_type][1] if class_type in _LOADERS else "image"
    if class_type == "LoadImageMask":
        inputs.update({field_name: name, "channel": _MASK_CHANNEL})
    elif class_type == "LoadImage" and {slot for _, _, slot in _consumers(api).get(node_id, [])} == {1}:
        node["class_type"] = "LoadImageMask"
        node["inputs"] = {"image": name, "channel": _MASK_CHANNEL}
        for other in api.values():
            for key, value in (other.get("inputs") or {}).items():
                if isinstance(value, list) and len(value) >= 2 and str(value[0]) == node_id and value[1] == 1:
                    other["inputs"][key] = [value[0], 0]
    else:
        inputs[field_name] = name
    return api


def set_value(api: dict[str, Any], key: str, value: Any, titles: dict[str, str] | None = None) -> bool:
    """按 `<节点 id>.<输入名>` 或 `<节点标题>.<输入名>` 改一个字面量输入。改到了回 True。

    给智能体用的写法:它从 `list_workflows` 里看到的是节点 id 和标题,两种都该认。标题里可能有点号,
    所以输入名按**最后一个**点切。
    """
    head, dot, name = str(key).rpartition(".")
    if not dot or not head or not name:
        return False
    titles = titles or {}
    targets = [head] if head in api else [node_id for node_id, title in titles.items() if title == head]
    changed = False
    for node_id in targets:
        node = api.get(node_id)
        if isinstance(node, dict) and name in (node.get("inputs") or {}) and _literal(node["inputs"][name]):
            node["inputs"][name] = value
            changed = True
    return changed


# ---------------------------------------------------------------------------
# 收:跑完的图交出了什么
# ---------------------------------------------------------------------------

#: ComfyUI 输出节点把文件记在这几个键下面:SaveImage → images,VHS → gifs,新的视频节点 → videos。
OUTPUT_KEYS = ("images", "gifs", "videos", "audio")
#: 显示文字的节点把字记在这几个键下面(ShowText → text,PreviewAny → text / string)。
TEXT_KEYS = ("text", "string", "texts")
VIDEO_SUFFIXES = (".mp4", ".webm", ".mov", ".mkv", ".gif", ".webp", ".avi")
AUDIO_SUFFIXES = (".wav", ".mp3", ".flac", ".ogg", ".opus", ".m4a", ".aac")


def media_of(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(AUDIO_SUFFIXES):
        return "audio"
    if lower.endswith((".mp4", ".webm", ".mov", ".mkv", ".avi")):
        return "video"
    if lower.endswith((".gif", ".webp")):
        # 动图也可能是一张静图(webp);按「交出它的是不是视频节点」再判一次,见 all_outputs
        return "animated"
    return "image"


def all_outputs(history_entry: dict[str, Any], *, include_previews: bool = False,
                prompt: dict[str, Any] | None = None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """一张跑完的图交出的**全部**东西:(文件, 文字)。

    文件每一项 `{node, class_type, item, media}`,按节点顺序;存下来的(type=output)总在,预览
    (type=temp)只在要求时或一份存下来的都没有时才算 —— 只接了 PreviewImage 的图也能交出东西,
    而同时有 SaveImage 和 PreviewImage 的图,预览多半是中间结果。
    文字每一项 `{node, class_type, text}`(反推提示词、描述图片这类工作流的产出就是一段字)。
    """
    if prompt is None:
        # 历史条目里的 `prompt` 是 [序号, 任务号, 那张 API 图, 附加信息, 要跑的输出节点]
        recorded = history_entry.get("prompt")
        prompt = recorded[2] if isinstance(recorded, list) and len(recorded) > 2 and isinstance(recorded[2], dict) else {}
    outputs = history_entry.get("outputs") or {}
    files: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    for node_id in sorted(outputs, key=lambda one: _node_order(str(one))):
        node_output = outputs[node_id]
        if not isinstance(node_output, dict):
            continue
        class_type = str((prompt.get(str(node_id)) or {}).get("class_type", ""))
        for key in OUTPUT_KEYS:
            for item in node_output.get(key) or []:
                if isinstance(item, dict) and item.get("filename"):
                    media = media_of(str(item["filename"]))
                    if media == "animated":
                        media = "video" if key in ("gifs", "videos") or class_type in _VIDEO_OUTPUT_TYPES else "image"
                    if key == "audio":
                        media = "audio"
                    files.append({"node": str(node_id), "class_type": class_type, "item": item, "media": media})
        for key in TEXT_KEYS:
            values = node_output.get(key)
            for value in values if isinstance(values, list) else ([values] if isinstance(values, str) else []):
                if isinstance(value, str) and value.strip():
                    texts.append({"node": str(node_id), "class_type": class_type, "text": value})
    saved = [one for one in files if one["item"].get("type") != "temp"]
    if not include_previews and saved:
        files = saved
    return files, texts


def collect_outputs(history_entry: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    """一次**生成**要交回的文件:这次要的那一种(图 / 视频 / 音频),全部。

    存下来的优先;一个都没有才用预览 —— 只接了 PreviewImage 的图也能出东西。视频图里常常同时有逐帧的图
    和合成的视频:要的是视频那几份,不是第一帧。
    """
    files, _ = all_outputs(history_entry, include_previews=True)
    wanted = [one for one in files if one["media"] == kind]
    # 这一种里存下来的优先;一份都没存(VHS 关了 save_output)才用预览 —— 不拿别的种类顶替
    saved = [one["item"] for one in wanted if one["item"].get("type") != "temp"]
    if saved or wanted:
        return saved or [one["item"] for one in wanted]
    # 认不出种类(没有后缀的文件名之类):照旧交回第一份,总比说「没有产出」强
    fallback = [one for one in files if one["item"].get("type") != "temp"] or files
    return [one["item"] for one in fallback][:1]


def interrupted(status: dict[str, Any]) -> bool:
    """这个任务是被中断的(ComfyUI 界面上点了中断、别人 /interrupt 了它),不是跑出了错。"""
    return any(isinstance(message, list) and message and message[0] == "execution_interrupted"
               for message in status.get("messages") or [])


def execution_error(status: dict[str, Any]) -> str:
    """ComfyUI 自己说的失败原因;一句都没有就是空串。"""
    for message in reversed(status.get("messages") or []):
        if isinstance(message, list) and len(message) == 2 and message[0] == "execution_error":
            payload = message[1] or {}
            node = payload.get("node_type") or ""
            said = payload.get("exception_message") or ""
            return f"{node}: {said}".strip(": ") if said or node else "execution_error"
    return ""


#: 校验错误里一条 details 最多留多少字:「Value not in list」的 details 带着整张可选值列表。
_MAX_DETAIL = 160


def validation_errors(detail: dict[str, Any]) -> str:
    """`/prompt` 回 400 时的校验错误:顶层那句 + 每个节点的每一条(details 截短)。"""
    lines: list[str] = []
    top = detail.get("error")
    if isinstance(top, dict) and top.get("message"):
        # 「节点不存在 / 自定义节点没装」这类只有顶层一句,details 里说的是哪个节点
        extra = str(top.get("details") or "")[:_MAX_DETAIL]
        lines.append(f"{top['message']}{(' (' + extra + ')') if extra else ''}")
    for node_id, node in (detail.get("node_errors") or {}).items():
        for problem in (node or {}).get("errors") or []:
            said = problem.get("message") if isinstance(problem, dict) else problem
            extra = str(problem.get("details") or "") if isinstance(problem, dict) else ""
            if len(extra) > _MAX_DETAIL:
                extra = extra[:_MAX_DETAIL] + "…"
            lines.append(f"#{node_id} {said}{(': ' + extra) if extra else ''}")
    return "; ".join(lines)
