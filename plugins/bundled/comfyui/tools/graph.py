"""ComfyUI 的 API 图:看出一张图能调什么、把 Mosael 的请求填进去、收产出。

「ComfyUI 内部格式」的知识只在插件里(这个文件和 convert.py):它们跟着 ComfyUI 的版本变(新的采样器节点、
新的视频输出节点),所以住在插件里跟着插件走,而不是住在应用内核里跟着应用发版(ADR 0020)。
UI 图(保存的工作流)怎么变成这里吃的 API 图,见 convert.py。
"""

from __future__ import annotations

import copy
import random
import re
from dataclasses import dataclass
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
#: CLIPTextEncodeSDXL 分成 text_g / text_l —— 同一句话写进每一格。没有 CLIP 编码节点的那几类,提示词是生成节点
#: 自己的一格:MiniMax H3 / ByteDance / Kling / Veo 的 `prompt`,MiniMax / 海螺 API 节点的 `prompt_text`,
#: WanVideoWrapper 的 WanVideoTextEncode 的 `positive_prompt`。
_TEXT_INPUTS = ("text", "clip_l", "t5xxl", "text_g", "text_l", "prompt", "prompt_text", "positive_prompt")
#: 反向提示词和正向的写在**同一个节点**上时(Kling、Veo 的 API 节点,WanVideoTextEncode)叫这几个名字。
_NEGATIVE_INPUTS = ("negative_prompt", "negative_prompt_text")
#: 后端的「一段文字」节点:提示词常常写在它身上,再连进 CLIPTextEncode 的 text(新版的模板就这么排)。
_STRING_SOURCES = frozenset({"PrimitiveString", "PrimitiveStringMultiline"})
#: 一个节点**整个就是一段字**(连进提示词那一格的上游)时,字放在哪几格:后端的 PrimitiveString 是 `value`,
#: 各家自定义的「Text」「String」节点多半是 `text` / `string`。
_STRING_FIELDS = ("value", "text", "string")
#: 这些节点**生成画布**:宽高写在它们身上就是成片的尺寸。
_SIZE_NODE_TYPES = frozenset(
    {"WanImageToVideo", "WanFirstLastFrameToVideo", "WanVaceToVideo", "HunyuanImageToVideo", "LTXVImgToVideo",
     "CosmosImageToVideoLatent", "Wan22ImageToVideoLatent"}
)
#: 这些输入名说明参考图是**首帧**(视频从它开始动)/**尾帧**。合作方 API 节点各叫各的:海螺 `first_frame_image`,
#: Kling、Runway `start_frame` / `end_frame`,Luma `first_image` / `last_image`。
_FIRST_FRAME_INPUTS = frozenset({"start_image", "first_frame", "init_image", "first_frame_image", "start_frame",
                                 "first_image"})
_LAST_FRAME_INPUTS = frozenset({"end_image", "last_frame", "end_frame", "last_frame_image", "last_image"})
#: 输出节点 → 这张图产出什么。CreateVideo **不是**输出节点:它把帧和声音合成一段视频交给下游(SaveVideo 才存),
#: 算进来的话一张「CreateVideo → SaveVideo」的图就成了两个视频产出。
_VIDEO_OUTPUT_TYPES = frozenset({"VHS_VideoCombine", "SaveVideo", "SaveWEBM", "SaveAnimatedWEBP", "SaveAnimatedPNG"})
#: 核心节点里带「Advanced」的两个(ComfyUI 0.39 的 comfy_extras:选格式的保存节点)也是成品 —— 维护者的
#: 「minimax+music3+文生音乐」只有 SaveAudioAdvanced 一个输出,此前被当成交不出音频的图像模型。
_AUDIO_OUTPUT_TYPES = frozenset({"SaveAudio", "SaveAudioMP3", "SaveAudioOpus", "SaveAudioAdvanced", "PreviewAudio"})
_IMAGE_OUTPUT_TYPES = frozenset({"SaveImage", "SaveImageAdvanced", "PreviewImage", "Image Save", "SaveImageWebsocket"})
#: 把文字显示出来的输出节点(描述图片、反推提示词这一类工作流的产出就是一段字)。
_TEXT_OUTPUT_TYPES = frozenset({"ShowText|pysssss", "PreviewAny", "PreviewText", "Display Any (rgthree)",
                                "ShowText", "easy showAnything"})
_SAVE_NODE_TYPES = _VIDEO_OUTPUT_TYPES | _AUDIO_OUTPUT_TYPES | _IMAGE_OUTPUT_TYPES
#: 只把结果写进 ComfyUI 临时目录的输出节点(历史里记成 `type: temp`):看一眼用的,不是这张图的成品 ——
#: 放大图里预览的是读进来的原图,ControlNet 图里预览的是预处理出来的线稿 / 深度图。
_PREVIEW_OUTPUT_TYPES = frozenset({"PreviewImage", "PreviewAudio"})

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
    """这个节点上存着提示词文字的那几格(字面量字符串):正向的和同一个节点上的反向的。"""
    inputs = node.get("inputs") or {}
    names = ("value",) if str(node.get("class_type", "")) in _STRING_SOURCES else (*_TEXT_INPUTS, *_NEGATIVE_INPUTS)
    return [name for name in names if name in inputs and _literal(inputs[name]) and isinstance(inputs[name], str)]


def _string_fields(node: dict[str, Any]) -> list[str]:
    """一个**连进提示词那一格**的上游节点上存着那段字的几格(它整个就是一段字:PrimitiveString、自定义的 Text…)。"""
    inputs = node.get("inputs") or {}
    return [name for name in (*_STRING_FIELDS, *_TEXT_INPUTS)
            if name in inputs and _literal(inputs[name]) and isinstance(inputs[name], str)]


def _multiline_text(object_info: dict[str, Any] | None, class_type: str, name: str) -> bool:
    """ComfyUI 说这一格是**多行的字符串**(提示词框)。不认识这个节点(自定义节点没装在给的 object_info 里)就不拦,
    按名字认 —— 名字本身就在提示词那几个里。"""
    defs = _input_defs(object_info or {}, class_type)
    if not defs or name not in defs:
        return True
    definition = defs[name]
    if not isinstance(definition, list) or not definition or definition[0] != "STRING":
        return False
    options = definition[1] if len(definition) > 1 and isinstance(definition[1], dict) else {}
    return options.get("multiline") is True


def _trace_text_node(api: dict[str, Any], ref: Any, prefer: str, seen: set[str]) -> tuple[str, list[str]] | None:
    """从 [节点, 槽位] 往上游追到写提示词的节点,穿过 ControlNetApply、FluxGuidance 这类条件处理节点。
    交回 (节点, 字写在哪几格)。"""
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
    fields = text_fields(node)
    if fields:
        return node_id, fields
    for key in _TEXT_INPUTS:
        # 文字从一个「一段文字」节点连进来:提示词写在那个节点上(后端的 PrimitiveString、自定义的 Text 节点…)
        source = inputs.get(key)
        upstream = api.get(str(source[0])) if isinstance(source, list) and source else None
        if isinstance(upstream, dict) and _string_fields(upstream):
            return str(source[0]), _string_fields(upstream)
    for key in (prefer, "conditioning", "positive", "negative"):  # 优先同名槽,正负不混
        found = _trace_text_node(api, inputs.get(key), prefer, seen)
        if found is not None:
            return found
    return None


def _role_of(field: str, role: str) -> str:
    return "negative" if field in _NEGATIVE_INPUTS else role


def text_slots(api: dict[str, Any], object_info: dict[str, Any] | None = None) -> dict[tuple[str, str], str]:
    """写提示词的那几格:`(节点, 输入名)` → "prompt" / "negative"。

    先从采样器和引导器的 positive / conditioning / negative 往上游追(KSampler、Flux 的 BasicGuider、MiniMax H3 的
    BasicGuider → MiniMaxH3ImageToVideo)。那一路**一句正向的都没找到**(没有 ComfyUI 认得的采样器:合作方 API 节点、
    WanVideoWrapper 这类自带采样器的包),就从产出节点往上游找:接到产出上的节点里,名字是提示词的、ComfyUI 说是
    多行字符串的字面量就是提示词(见 `_upstream_texts`)。同一个节点上叫 `negative_prompt` 的那格是反向提示词。
    """
    slots: dict[tuple[str, str], str] = {}
    for node in api.values():
        class_type = str(node.get("class_type", ""))
        inputs = node.get("inputs") or {}
        if class_type in _SAMPLER_TYPES or _GUIDER_MARK in class_type:
            for slot, role in (("positive", "prompt"), ("conditioning", "prompt"), ("negative", "negative")):
                found = _trace_text_node(api, inputs.get(slot), slot, set())
                if found is None:
                    continue
                target, fields = found
                for field in fields:
                    slots.setdefault((target, field), _role_of(field, role))
    if "prompt" not in slots.values():
        for key, role in _upstream_texts(api, object_info).items():
            slots.setdefault(key, role)
    return slots


def _upstream_texts(api: dict[str, Any], object_info: dict[str, Any] | None) -> dict[tuple[str, str], str]:
    """从交出文件的产出节点往上游走,写在路过的节点上的提示词(按节点顺序)。

    认的是**名字**(提示词那几格:`prompt`、`prompt_text`、`positive_prompt`、`text`…)加上 **ComfyUI 说的类型**
    (多行字符串,见 `_multiline_text`)—— 一格单行的 `prompt`(id、文件名前缀)不算。只走接到产出上的节点:
    一个没接上的文字节点什么都不影响。连进提示词那一格的上游(一个整个就是一段字的节点)也算,字写在它身上。
    """
    outputs = [node["node"] for node in output_nodes(api, object_info) if node["media"] != "text"]
    #: (节点, 这一路是正向还是反向):顺着 `negative` 那一格走上去的整条支路都是反向的(自定义采样器的
    #: positive / negative 各接一个 CLIPTextEncode,两个都只叫 `text`)。
    queue: list[tuple[str, str]] = [(node_id, "prompt") for node_id in outputs]
    seen: set[tuple[str, str]] = set()
    found: dict[tuple[str, str], str] = {}
    while queue:
        node_id, branch = queue.pop(0)
        if (node_id, branch) in seen or not isinstance(api.get(node_id), dict):
            continue
        seen.add((node_id, branch))
        node = api[node_id]
        class_type = str(node.get("class_type", ""))
        for name, value in (node.get("inputs") or {}).items():
            named = name in _TEXT_INPUTS or name in _NEGATIVE_INPUTS
            role = "negative" if branch == "negative" or name in _NEGATIVE_INPUTS else "prompt"
            if isinstance(value, list) and value:
                upstream_id = str(value[0])
                upstream = api.get(upstream_id)
                if named and isinstance(upstream, dict) and _string_fields(upstream):
                    for field in _string_fields(upstream):
                        found.setdefault((upstream_id, field), role)
                queue.append((upstream_id, "negative" if name.startswith("negative") else branch))
            elif named and isinstance(value, str) and _multiline_text(object_info, class_type, name):
                found.setdefault((node_id, name), role)
    return dict(sorted(found.items(), key=lambda pair: _node_order(pair[0][0])))


def prompt_requirement(api: dict[str, Any], slots: dict[tuple[str, str], str] | None = None,
                       placeholders: set[str] | None = None, *, object_info: dict[str, Any] | None = None) -> str:
    """这张图对提示词的要求(宿主描述符的 `prompt`,见 docs/PLUGIN_MANIFEST 的「替宿主做生成」):

    - `required`:模板里有 `{{prompt}}` 占位符(没有默认值,不填就是一句字面的占位符),或者写提示词的节点里有一个
      存着的是空串 —— 不写的话那张图拿空话去跑;
    - `optional`:有写提示词的节点,而且**每一个都存着一句话** —— 不写就用这张图自己那句,写了就换成你的;
    - `none`:没有任何提示词(放大、抠图、修脸、补帧这类「处理一份素材」的图)。宿主不摆提示词框,
      也不逼人敲一句没用的话。

    判的是**真的喂进生成的**文字(见 text_slots),不是图里有没有 CLIPTextEncode:一个没接上的文字节点什么都
    不影响。反向提示词不算 —— 它有自己的控件。
    """
    placeholders = _placeholders_in(api) if placeholders is None else placeholders
    if "prompt" in placeholders:
        return "required"
    slots = text_slots(api, object_info) if slots is None else slots
    positive: dict[str, list[str]] = {}
    for (node_id, field), role in slots.items():
        if role == "prompt":
            positive.setdefault(node_id, []).append(field)
    if not positive:
        return "none"
    for node_id, fields in positive.items():
        inputs = api[node_id].get("inputs") or {}
        if not any(str(inputs.get(name) or "").strip() for name in fields):
            return "required"
    return "optional"


#: ComfyUI「生成后怎样」里会换种子的那几种。别的值(fixed,以及 rgthree「Seed」后面那几格按钮存下来的空串)都是不换。
_CHANGING_CONTROLS = frozenset({"randomize", "increment", "decrement"})


def _changes_each_run(node: dict[str, Any], name: str) -> bool:
    meta = node.get("_meta") if isinstance(node.get("_meta"), dict) else {}
    controls = meta.get(convert.CONTROLS) if isinstance(meta.get(convert.CONTROLS), dict) else {}
    return controls.get(name) in _CHANGING_CONTROLS


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


def counts_runs(api: dict[str, Any]) -> bool:
    """这张图的「张数」是**跑几遍**:出图的、有种子可换(每遍换一个种子才出得来不一样的图)。

    每遍按工作流原样跑 —— 画布上存着的 batch_size 照旧,一遍出几张是工作流自己定的(见 images_per_run);张数不写进
    batch_size。没有种子的(放大、抠图)跑几遍都是同一张,不给张数;视频图不给。
    """
    return kind_of(api) == "image" and bool(seed_inputs(api) or "seed" in _placeholders_in(api))


def _batch_of(api: dict[str, Any], node_id: str) -> int | None:
    """一遍下来这个输出节点收到几张:它上游存着的那个字面量 `batch_size`(画布、潜空间)。上游没有、或者存着几个
    不一样的(判不了是哪个),是 None —— 一遍出几张由工作流自己定,只能按 1 张摆占位。"""
    found = {value for one in _upstream_closure(api, {node_id})
             if isinstance(value := (api[one].get("inputs") or {}).get("batch_size"), int) and not isinstance(value, bool)}
    return found.pop() if len(found) == 1 else None


def images_per_run(api: dict[str, Any], nodes: list[dict[str, str]]) -> int:
    """跑一遍这几个输出节点一共交回几张:每个节点收到的批量(判不了按 1)加起来。"""
    return sum(_batch_of(api, node["node"]) or 1 for node in nodes)


def shared_batch(api: dict[str, Any], nodes: list[dict[str, str]]) -> int | None:
    """这几个输出节点一遍各收到几张 —— 都一样、而且判得出来时是那个数,否则 None(给人看的说明就不写批量)。"""
    found = {_batch_of(api, node["node"]) for node in nodes}
    return found.pop() if len(found) == 1 else None


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


#: 一格输入的名字说明接进来的是**参考**:`ref_images.ref_image_0`、`ref_videos.*`、`reference_video`、`ref_audio`…
_REFERENCE_INPUT = re.compile(r"^(ref|reference)(_|s?\.|$)", re.IGNORECASE)
#: 图进生成节点之前常先过一两道「图 → 图」的处理(缩放、裁切、调色、加水印):接在这几格上的,顺着它的第一个输出
#: (图)往下找它最后进了哪儿。
_IMAGE_PASSES = frozenset({"image", "images"})
_FRAME_HOPS = 4


def _frame_role(api: dict[str, Any], node_id: str) -> str:
    """视频图里一张读进来的图是首帧、尾帧还是参考图:看它(或它缩放、裁切之后的那张)接进了哪一格。"""
    downstream: dict[str, list[tuple[str, str, str, int]]] = {}
    for consumer, node in api.items():
        for name, value in (node.get("inputs") or {}).items():
            if isinstance(value, list) and len(value) >= 2:
                slot = value[1] if isinstance(value[1], int) else 0
                downstream.setdefault(str(value[0]), []).append((consumer, str(node.get("class_type", "")), name, slot))
    frontier, seen = [node_id], {node_id}
    for _ in range(_FRAME_HOPS):
        following: list[str] = []
        for current in frontier:
            for consumer, class_name, name, slot in downstream.get(current, []):
                if slot != 0:
                    continue
                if name in _FIRST_FRAME_INPUTS or (name == "image" and "ImageToVideo" in class_name):
                    return "first_frame"
                if name in _LAST_FRAME_INPUTS:
                    return "last_frame"
                if name in _IMAGE_PASSES and consumer not in seen:
                    seen.add(consumer)
                    following.append(consumer)
        frontier = following
    return "reference_image"


def slots(api: dict[str, Any], kind: str, titles: dict[str, str] | None = None) -> list[dict[str, str]]:
    """读素材的节点 → 输入槽位 `{node, class_type, title, media, field, role}`,按节点顺序。

    角色看它**接到哪儿**(宿主的素材角色,见 ai/providers/contracts/generation.SOURCE_ROLES):

    - 图:视频图里接到 start_image 这类输入的是首帧、接到 end_image 的是尾帧(先过一道缩放、裁切再接进去的也算,
      见 _frame_role),其余是参考图;
      只用了 LoadImage 的第二个输出(alpha 当蒙版)的,是蒙版;
    - LoadImageMask:蒙版;
    - 视频(LoadVideo / VHS_LoadVideo):被改的那一段(源视频);
    - 音频:视频图里是驱动音频(口型、卡点),别的图里是参考音频;
    - 接在**参考**那几格上的(MiniMax H3 多参考生视频的 `ref_images.*` / `ref_videos.*` / `ref_audios.*`,
      `reference_video` 这类)就是参考:参考视频不是要改的那一段(那是必给的),参考音频也不是驱动口型的音频
      (那要数字人授权)。
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
        referenced = any(_REFERENCE_INPUT.match(name) for _, name, _ in used)
        if media == "image":
            outputs_used = {slot for _, _, slot in used}
            if outputs_used == {1}:
                media, role = "mask", "mask"
            elif kind == "video":
                role = _frame_role(api, node_id)
        elif media == "mask":
            role = "mask"
        elif media == "video":
            role = "reference_video" if referenced else "source_video"
        elif media == "audio":
            role = "driving_audio" if kind == "video" and not referenced else "reference_audio"
        found.append({
            "node": node_id,
            "class_type": class_type,
            "title": titles.get(node_id) or class_type,
            "media": media,
            "field": field_name,
            "role": role,
        })
    return found


def alpha_masks(api: dict[str, Any], found_slots: list[dict[str, str]]) -> list[dict[str, str]]:
    """拿 LoadImage 的 **alpha 当蒙版**的那几张图(图和 alpha 两路都接下去,ComfyUI 蒙版编辑器画的就在 alpha 里)。
    图里没有单独的蒙版槽时,给的蒙版替掉 alpha 那一路(见 wire_inputs)—— 生成和工具都收一份蒙版。"""
    if any(slot["media"] == "mask" for slot in found_slots):
        return []
    consumers = _consumers(api)
    return [slot for slot in found_slots if slot["media"] == "image"
            and {used for _, _, used in consumers.get(slot["node"], [])} >= {0, 1}]


def features(api: dict[str, Any], found_slots: list[dict[str, str]] | None = None,
             object_info: dict[str, Any] | None = None) -> list[str]:
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
    if text_slots(api, object_info):
        tags.append("prompt")
    return tags


def output_nodes(api: dict[str, Any], object_info: dict[str, Any] | None = None,
                 titles: dict[str, str] | None = None) -> list[dict[str, str]]:
    """会交出东西的节点 `{node, class_type, title, label, media}`(`label` 是给人看的节点名,见 labels.node_name)。

    ComfyUI 在 object_info 里给每个节点标了是不是输出节点(`output_node`)—— 标了就信它(自定义节点也认得出,
    标着 false 的也不算);没标的(没给 object_info、没装的节点)按已知的几类认。再按已知的几类说它交出的是图、
    视频、音频还是一段字。

    **只预览预处理结果的预览节点不算**(见 `_previews_input`):一张会生成东西的图里,看一眼骨架、线稿、深度图
    或读进来的原图的那个 PreviewImage 不是产出。
    """
    titles = titles or {}
    object_info = object_info or {}
    found: list[dict[str, str]] = []
    for node_id in sorted(api, key=_node_order):
        class_type = str(api[node_id].get("class_type", ""))
        info = object_info.get(class_type) if isinstance(object_info.get(class_type), dict) else {}
        if not (info["output_node"] is True if "output_node" in info else class_type in _KNOWN_OUTPUT_TYPES):
            continue
        if _previews_input(api, node_id):
            continue
        found.append({"node": node_id, "class_type": class_type, "title": titles.get(node_id) or class_type,
                      "label": labels.node_name(class_type, titles.get(node_id, ""), object_info),
                      "media": output_media(class_type)})
    return found


_KNOWN_OUTPUT_TYPES = _VIDEO_OUTPUT_TYPES | _AUDIO_OUTPUT_TYPES | _IMAGE_OUTPUT_TYPES | _TEXT_OUTPUT_TYPES
#: 类名里带它的节点把潜空间**解码**成图 / 声音(VAEDecode、VAEDecodeTiled、VAEDecodeAudio、WanVideoDecode …):
#: 采样出来的东西要经过它才变成能看的图。
_DECODE_MARK = "Decode"


def _previews_input(api: dict[str, Any], node_id: str) -> bool:
    """这个预览节点只是在看预处理的结果(或读进来的原图),不是这张图的产出。

    判据只看连线:图里有解码节点(这是一张会生成东西的图),而这个预览节点(PreviewImage / PreviewAudio)的上游
    一个解码节点都没有 —— 它看的是 LoadImage 读进来的、或预处理器(OpenPose 骨架、Canny 线稿、深度图)从它算出来的
    东西,采样根本没参与。整张图都没有解码节点的(放大、抠图、合作方 API 节点)不判,预览照旧是产出。
    """
    if str(api[node_id].get("class_type", "")) not in _PREVIEW_OUTPUT_TYPES:
        return False
    decoders = {one for one, node in api.items() if _DECODE_MARK in str(node.get("class_type", ""))}
    return bool(decoders) and not (_upstream_closure(api, {node_id}) & decoders)


def _links_of(node: dict[str, Any]) -> list[str]:
    """这个节点的输入接着哪几个上游节点。"""
    return [str(value[0]) for value in (node.get("inputs") or {}).values() if isinstance(value, list) and len(value) == 2]


def _upstream_closure(api: dict[str, Any], roots: set[str]) -> set[str]:
    """`roots` 连同它们的全部上游。"""
    found: set[str] = set()
    queue = [one for one in roots if one in api]
    while queue:
        node_id = queue.pop()
        if node_id in found:
            continue
        found.add(node_id)
        queue.extend(one for one in _links_of(api[node_id]) if one in api and one not in found)
    return found


def _is_socket(definition: Any) -> bool:
    """这一格输入是一个**插口**(只能接线:MODEL、LATENT、IMAGE…),不是 widget。"""
    if not isinstance(definition, list) or not definition:
        return False
    options = definition[1] if len(definition) > 1 and isinstance(definition[1], dict) else {}
    if options.get("forceInput"):
        return True
    kind = options.get("widgetType") or definition[0]
    return not (isinstance(kind, list) or kind in convert.WIDGET_TYPES)


def _missing_socket(node: dict[str, Any], object_info: dict[str, Any]) -> bool:
    """一格必填的插口没接上(上游被静音,线随之断了):ComfyUI 校验这个节点必然失败,靠它的输出节点出不来。"""
    required = ((object_info.get(str(node.get("class_type", ""))) or {}).get("input") or {}).get("required") or {}
    inputs = node.get("inputs") or {}
    return any(name not in inputs and _is_socket(definition) for name, definition in required.items())


def live(api: dict[str, Any], object_info: dict[str, Any]) -> dict[str, Any]:
    """ComfyUI **真会跑**的那部分图:能跑的输出节点和它们的上游,别的都不算(返回新图,不改入参)。

    ComfyUI 只执行输出节点要的那些节点;一个输出节点的上游缺了必填的插口(第一遍文生图的 KSampler 被静音,
    后面的 VAEDecode 就没了 samples),它校验不过、什么都交不出,别的输出照跑。可图上那些悬空的节点此前照样被
    当成这张图的一部分:悬空的 EmptyLatentImage 成了「尺寸」「张数」(选 2 张,batch_size 写进一个没人用的节点),
    下游全被旁路的 LoadImage 成了一格输入,出不来的 PreviewImage 算进「一次交回几份」。

    判不了的不替 ComfyUI 拿主意,原样留着:没装的节点(object_info 里没有它,不知道它是不是输出)连同上游都留下,
    ComfyUI 会说出缺了什么;输出节点全断了、或者一个输出都没有,整张图原样交回去让 ComfyUI 说原因。
    """
    if not object_info:
        return api
    outputs = {node["node"] for node in output_nodes(api, object_info)}
    unknown = {node_id for node_id, node in api.items() if str(node.get("class_type", "")) not in object_info}
    broken = {node_id for node_id, node in api.items() if _missing_socket(node, object_info)}
    runnable = {node_id for node_id in outputs if not _upstream_closure(api, {node_id}) & broken}
    keep = _upstream_closure(api, (runnable or outputs) | unknown)
    if not outputs or not keep:
        return api
    return {node_id: node for node_id, node in api.items() if node_id in keep}


def media_outputs(api: dict[str, Any], object_info: dict[str, Any] | None = None,
                  titles: dict[str, str] | None = None) -> list[dict[str, str]]:
    """会交出**文件**的输出节点:图、视频、音频,以及认不出种类的自定义输出节点(多半是某种保存节点)。

    只交出一段字的(反推提示词、打标签)不算 —— 这种图**不是生成模型**:生成是「一段提示词 → 一份成片」,
    它交不出成片,`kind_of` 却会把它兜成 image,选了它的生成永远拿不回一张图。它照样是一个工具(见 tooling)。
    """
    return [node for node in output_nodes(api, object_info, titles) if node["media"] != "text"]


def persists(node: dict[str, Any]) -> bool:
    """这个输出节点交出的文件**存下来**吗(历史里是 `type: output`),还是只是预览(`type: temp`)。

    预览节点(PreviewImage、PreviewAudio)不存;视频合成(VHS_VideoCombine)关了 `save_output` 也只是预览。
    和 `all_outputs` / `collect_outputs` 按历史里的 `type` 分的是同一件事,这里是跑之前在图上判。
    """
    class_type = str(node.get("class_type", ""))
    if class_type in _PREVIEW_OUTPUT_TYPES:
        return False
    inputs = node.get("inputs") if isinstance(node.get("inputs"), dict) else {}
    return not (class_type == "VHS_VideoCombine" and inputs.get("save_output") is False)


def generation_nodes(api: dict[str, Any], kind: str, object_info: dict[str, Any] | None = None,
                     titles: dict[str, str] | None = None) -> list[dict[str, str]]:
    """一次**生成**交回的是哪几个输出节点的文件 —— 和 `collect_outputs` 同一个判据,只是跑之前在图上判:

    这一种(`kind`)的输出节点里存下来的那几个;一个都不存(只接了 PreviewImage、VHS 关了 save_output)才是这一种的
    预览节点。别的种类不算(视频图里逐帧的预览不是成片)。工具那边判「这张图就是一个生成模型」(tooling._mirror)
    问的就是这一份,两边对「产出是什么」说的是同一句话。
    """
    wanted = [node for node in output_nodes(api, object_info, titles) if node["media"] == kind]
    saved = [node for node in wanted if persists(api.get(node["node"]) or {})]
    return saved or wanted


def _link(value: Any) -> tuple[str, int] | None:
    """一格输入接着的那份输出 `(节点 id, 第几个输出)`;不是连线是 None。"""
    if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
        return str(value[0]), value[1]
    return None


def _readers(api: dict[str, Any]) -> dict[tuple[str, int], set[str]]:
    """每一份输出(`(节点 id, 第几个输出)`)→ 接着用它的那些节点。"""
    found: dict[tuple[str, int], set[str]] = {}
    for node_id, node in api.items():
        for value in (node.get("inputs") or {}).values():
            link = _link(value)
            if link:
                found.setdefault(link, set()).add(node_id)
    return found


#: 输出节点上接着「它显示的那份东西」的那一格:图、视频、音频。都没有的(自定义的输出节点)看接进来的每一根线。
_SHOWN_INPUTS = ("images", "video", "audio")


def _shown(api: dict[str, Any], node_id: str) -> list[tuple[str, int]]:
    """一个输出节点**显示的那份东西**:接在 images / video / audio 上的那根线(VAE、视频旁边配的声音这类整张图共用的
    原料不算)。"""
    links = {name: link for name, value in ((api.get(node_id) or {}).get("inputs") or {}).items()
             if (link := _link(value))}
    return next(([links[name]] for name in _SHOWN_INPUTS if name in links), list(links.values()))


def _is_decoder(node: dict[str, Any]) -> bool:
    return _DECODE_MARK in str(node.get("class_type", ""))


def _made_from(api: dict[str, Any], node_id: str, readers: dict[tuple[str, int], set[str]]) -> set[str]:
    """拿这个输出显示的东西**接着做下去**的那些节点(它自己的上游里的不算)。

    显示的是一张解码出来的图时,连同它解的那份潜空间(`samples`)一起算:潜空间放大的两遍出图,第二遍接着采样的是
    那份潜空间,不是解出来的图。同一份潜空间另一个解码节点再解一遍不算「接着做」—— 看的还是同一遍。
    """
    mine = _upstream_closure(api, {node_id})
    users: set[str] = set()
    for source, slot in _shown(api, node_id):
        users |= readers.get((source, slot), set())
        decoder = api.get(source) or {}
        latent = _link((decoder.get("inputs") or {}).get("samples"))
        if latent and _is_decoder(decoder):
            users |= {one for one in readers.get(latent, set()) if not _is_decoder(api[one])}
    return users - mine


#: comfyui_controlnet_aux 的预处理器在 object_info 里的类别前缀:它们算出来的是控制图(骨架、深度、线稿、法线)。
_PREPROCESSOR_CATEGORY = "ControlNet Preprocessors"


def _input_types(object_info: dict[str, Any], node: dict[str, Any]) -> set[str]:
    """一个节点**接了线**的那几格输入是什么类型(IMAGE、MASK…),按 object_info 里它的定义。"""
    defs = _input_defs(object_info, str(node.get("class_type", "")))
    found: set[str] = set()
    for name, value in (node.get("inputs") or {}).items():
        definition = defs.get(name)
        if _link(value) and isinstance(definition, list) and definition and isinstance(definition[0], str):
            found.add(definition[0])
    return found


def auxiliary_view(api: dict[str, Any], node_id: str, object_info: dict[str, Any] | None) -> str:
    """这个输出看的是**辅助图**而不是成图:`control`(ControlNet 预处理器算出来的控制图)、`mask`(把一张蒙版画成的图),
    都不是就是空串。认的是 object_info 里节点定义的类别和插口类型,不认节点标题;没有 object_info 判不了,当成图。

    MeshGraphormer 从成图里认手:没认出手时那张深度图整张是黑的 —— 它是喂给 ControlNet 的,不是谁要的结果。
    """
    object_info = object_info or {}
    node = api.get(node_id) or {}
    if "MASK" in _input_types(object_info, node):
        return "mask"
    for source, _ in _shown(api, node_id):
        upstream = api.get(source) or {}
        spec = object_info.get(str(upstream.get("class_type", "")))
        if isinstance(spec, dict) and str(spec.get("category") or "").startswith(_PREPROCESSOR_CATEGORY):
            return "control"
        types = _input_types(object_info, upstream)
        if "MASK" in types and "IMAGE" not in types:
            return "mask"
    return ""


def final_outputs(api: dict[str, Any], nodes: list[dict[str, str]],
                  object_info: dict[str, Any] | None = None, marked: frozenset[str] = frozenset()) -> list[dict[str, str]]:
    """交回的这几个节点(`generation_nodes`)里哪几个是**最终结果**,其余的是中间一步或辅助图。

    **有标记就听标记**(ADR 0038 §5):用户在应用表单里把哪几个输出节点标成了结果(`marked`,「以后只要这张」),
    就是它们 —— 保存节点也能标(两个保存节点只要高清那张)。一个都没标(或标的都不在这一种里)才按下面猜:

    - **中间一步**:它显示的东西被**接着做下去**(见 `_made_from`),成了另一个输出的图 —— 两遍出图的第一遍、
      修脸(FaceDetailer)和放大之前的那张、拿去当 IP-Adapter 参考的那张、喂给 ControlNet 的控制图;
    - **辅助图**(`auxiliary_view`):控制图、蒙版。从不当结果,也不拿来判别人 —— 从成图里算一张深度图、抠一张
      蒙版拿去看,成图照样是结果。

    只看连线和节点定义,不看节点标题。只在预览节点之间挑:保存节点是工作流作者明说要存的,第一遍也存着的照样交回,
    存下来的仍然压过预览(`generation_nodes`)。整张图都没有解码节点的(放大、抠图、预处理工具、合作方 API 节点)
    不挑 —— 和 `_previews_input` 同一条线。一个都挑不出来就是全部。
    """
    picked = [node for node in nodes if node["node"] in marked]
    if picked:
        return picked
    if len(nodes) < 2 or any(persists(api.get(node["node"]) or {}) for node in nodes):
        return nodes
    if not any(_is_decoder(node) for node in api.values()):
        return nodes
    readers = _readers(api)
    main = [node for node in nodes if not auxiliary_view(api, node["node"], object_info)]
    finals = []
    for node in main:
        made = _made_from(api, node["node"], readers)
        if not any(made & (_upstream_closure(api, {other["node"]}) - {other["node"]}) for other in main if other is not node):
            finals.append(node)
    return finals or nodes


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

#: 尺寸下拉里**推荐**的几档(不是限制:任意宽高都收,每边取整到 SIZE_STEP 的倍数、至少 SIZE_MINIMUM)。
#: **这张图自己的尺寸**总在里面,且是默认值。
COMMON_SIZES = ("512x512", "768x768", "1024x1024", "832x1216", "1216x832", "1280x720", "720x1280", "1920x1080")
#: 「张数」(跑几遍)最多几遍:宿主一次生成的张数上限(见 ai/providers/contracts/generation.MAX_NUM_IMAGES)。
MAX_RUNS = 4
#: 宽高每边至少多少、取整到几的倍数。ComfyUI 的潜空间按 8 像素一格;生成的「尺寸」和工具的宽高是同一个规矩。
SIZE_MINIMUM = 16
SIZE_STEP = 8


def snap_side(value: Any) -> int:
    """一条边的像素数:四舍五入到 SIZE_STEP 的倍数,不小于 SIZE_MINIMUM。"""
    return max(SIZE_MINIMUM, int(float(value) / SIZE_STEP + 0.5) * SIZE_STEP)


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


def _tunable_entries(api: dict[str, Any], object_info: dict[str, Any],
                     titles: dict[str, str]) -> list[tuple[labels.Parameter, dict[str, Any], Any]]:
    """这张图里**给人调的**那些字面量输入:(描述好的参数, JSON Schema 片段, 人话名字),按常用程度排好。

    宿主自己有控件的(提示词、种子、尺寸)、画布上的批量(按工作流原样,见 counts_runs)、读素材的槽位、不该在 Mosael 里调的(文件名前缀)
    都不在这里。名字是人话(见 labels),原始的「节点 · 输入名」在 description 里。
    """
    prompts = text_slots(api, object_info)
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
            if (node_id, name) in prompts:
                continue  # 提示词 / 反向提示词
            if (node_id, name) in seeds:
                continue
            if node_id == sized and name in ("width", "height", "batch_size"):
                continue  # 尺寸是宿主的控件;一遍出几张按工作流原样(见 counts_runs),不在这里改
            if (node_id, name) in slot_fields or class_type in _LOADERS and name in ("image", "upload", "channel"):
                continue  # 读素材的槽位
            if labels.hidden_input(class_type, name, object_info):
                continue  # ComfyUI 自己的界面上就没有这一格(存示例提示词这类),不是给人调的
            spec = _schema(defs.get(name), value)
            if spec is None:
                continue
            folder = labels.model_folder(class_type, name)
            if folder and "enum" in spec:
                spec["x-model-folder"] = folder
            described = labels.describe(node_id, name, class_type, titles.get(node_id, ""), order, object_info)
            if not described.common or class_type in _SAVE_NODE_TYPES:
                spec["x-advanced"] = True
            spec["description"] = f"{titles.get(node_id) or class_type} · {name}"
            found.append((described, spec))
    found.sort(key=lambda pair: pair[0].rank)
    names = labels.titled([described for described, _ in found])
    return [(described, spec, names[described.key]) for described, spec in found]


def tunable(
    api: dict[str, Any],
    object_info: dict[str, Any],
    titles: dict[str, str] | None = None,
) -> dict[str, dict[str, Any]]:
    """这张图里**给人调的**那些字面量输入:`<节点 id>.<输入名>` → JSON Schema 片段,按常用程度排好(见 _tunable_entries)。"""
    return {described.key: {"title": name, **spec}
            for described, spec, name in _tunable_entries(api, object_info, titles or {})}


# ---------------------------------------------------------------------------
# 能填的项(ADR 0038 §1):生成目录、工具入参、应用表单都从这一份出发
# ---------------------------------------------------------------------------

#: 能填的项分哪几种。`text` / `media` 是节点上的一格(提示词、读素材的节点),中间四种是别的字面量 widget,
#: 最后三种是**图级**的(没有节点):种子写进每一处种子、尺寸写进画布节点、跑几遍是循环提交几次。
ITEM_KINDS = ("text", "media", "model", "number", "choice", "toggle", "seed", "size", "runs")
GRAPH_ITEMS = ("seed", "size", "runs")
#: 进参数表(`<节点 id>.<输入名>`)的那几种 —— 不是主提示词的文字也进。
VALUE_KINDS = frozenset({"text", "model", "number", "choice", "toggle"})


def _value_kind(spec: dict[str, Any]) -> str:
    if spec.get("x-model-folder"):
        return "model"
    if "enum" in spec:
        return "choice"
    if spec.get("type") == "boolean":
        return "toggle"
    if spec.get("type") in ("integer", "number"):
        return "number"
    return "text"


def slot_name(slot: dict[str, Any]) -> dict[str, str]:
    """一个读素材的槽位叫什么(`{"zh", "en"}`):用户给节点起的名字;没起就是「加载图像 #10」—— ComfyUI 给这类节点的名字
    加节点号(和「结果取自」里的节点名同一种写法,见 labels.node_name),不是类名。"""
    if slot["title"] != slot["class_type"]:
        return {"zh": slot["title"], "en": slot["title"]}
    name = slot.get("label") or labels.node_name(slot["class_type"])
    return {"zh": f"{name['zh']} #{slot['node']}", "en": f"{name['en']} #{slot['node']}"}


def plain(name: dict[str, str]) -> str | dict[str, str]:
    """一个名字交出去的样子:两种语言一样(用户起的标题)就是一句,不一样才按语言分开写。"""
    return name["zh"] if name["zh"] == name["en"] else name


def _size_spec(api: dict[str, Any], sized: str | None) -> dict[str, Any]:
    """「尺寸」:推荐的几档(`examples`),不是限制 —— 手填的任意宽高都收(宿主据此摆可以手填的下拉),每边按 8 的倍数取整。
    这张图自己的尺寸总在里面,且是默认值。"""
    size: dict[str, Any] = {"type": "string", "minimum": SIZE_MINIMUM, "multipleOf": SIZE_STEP}
    own = ""
    if sized is not None:
        inputs = api[sized]["inputs"]
        if isinstance(inputs.get("width"), int) and isinstance(inputs.get("height"), int):
            own = f"{inputs['width']}x{inputs['height']}"
    size["examples"] = ([own] if own else []) + [one for one in COMMON_SIZES if one != own]
    if own:
        size["default"] = own
    return size


def _runs_spec(api: dict[str, Any], delivering: list[dict[str, str]]) -> dict[str, Any]:
    """「张数」是跑几遍(见 run.generate):每遍按工作流原样,换一个种子;缺省跑一遍。宿主的「N×」是跑几遍 × 一遍几张。"""
    runs: dict[str, Any] = {"type": "integer", "minimum": 1, "maximum": MAX_RUNS, "default": 1, "x-count-unit": "runs"}
    batch = shared_batch(api, delivering)
    if batch is not None:
        runs["x-batch"] = batch  # 给人看的说明里写「批量 N」:一遍每个结果节点出几张
    return runs


def _pair(zh: str, en: str) -> dict[str, str]:
    return {"zh": zh, "en": en}


def items(api: dict[str, Any], object_info: dict[str, Any], titles: dict[str, str] | None = None) -> list[dict[str, Any]]:
    """这张图**全部能填的项**(ADR 0038 §1)。此前生成目录、工具入参各推各的那几步收在这一处:

    - 写提示词的那几格(`text`,带 `role`:prompt / negative,见 text_slots);
    - 读素材的节点(`media`,带 `role` 和 `media`,见 slots);
    - 图级的种子、尺寸、跑几遍(`seed` / `size` / `runs`,没有节点);
    - 其余给人调的字面量输入(见 _tunable_entries):选模型文件的下拉(`model`,带 `folder`)、别的下拉(`choice`)、
      开关(`toggle`)、数字(`number`)、文字(`text`,没有 `role`)。

    每项 `{key, node, input, kind, title, node_title, node_label?, hint?, class_type, common, schema?}`:`key` 是锚点
    (`<节点 id>.<输入名>`,图级的项就是它的名字),`title` 是人话名字(按语言分),`node_label` 是节点给人看的名字(用户起的
    标题、ComfyUI 给这类节点的名字,见 labels.node_name —— 编辑器按节点分组用它),`hint` 是 ComfyUI 给这一格的说明,
    `schema` 是它进参数表时的 JSON Schema 片段(读素材的没有)。类名(`class_type`)只给排错的悬停说明用。
    顺序:提示词、素材、图级的项、其余按常用程度。生成目录(describe)、工具(tooling.shape_of)、应用表单(app_form)都从它出发。
    """
    titles = titles or {}
    kind = kind_of(api)
    placeholders = _placeholders_in(api)
    found: list[dict[str, Any]] = []

    def node_facts(node_id: str) -> tuple[str, str, dict[str, str]]:
        class_type = str(api[node_id].get("class_type", ""))
        title = titles.get(node_id) or class_type
        return class_type, (title if title != class_type else ""), labels.node_name(class_type, title, object_info)

    def hinted(item: dict[str, Any], class_type: str, name: str) -> dict[str, Any]:
        hint = labels.input_hint(class_type, name, object_info)
        return {**item, "hint": hint} if hint else item

    prompts = text_slots(api, object_info)
    per_role: dict[str, int] = {}
    per_node: dict[tuple[str, str], int] = {}
    for (node_id, _field), role in prompts.items():
        per_role[role] = per_role.get(role, 0) + 1
        per_node[(node_id, role)] = per_node.get((node_id, role), 0) + 1
    for (node_id, field), role in prompts.items():
        class_type, custom, where = node_facts(node_id)
        zh, en = ("提示词", "Prompt") if role == "prompt" else ("反向提示词", "Negative prompt")
        if per_role[role] > 1:
            at = {"zh": custom, "en": custom} if custom else {lang: f"{where[lang]} #{node_id}" for lang in ("zh", "en")}
            if per_node[(node_id, role)] > 1:
                at = {lang: f"{at[lang]} · {field}" for lang in ("zh", "en")}
            zh, en = f"{zh} · {at['zh']}", f"{en} · {at['en']}"
        value = api[node_id]["inputs"][field]
        schema: dict[str, Any] = {"type": "string", "x-multiline": True}
        if isinstance(value, str):
            schema["default"] = value
        found.append(hinted({"key": f"{node_id}.{field}", "node": node_id, "input": field, "kind": "text", "role": role,
                             "title": _pair(zh, en), "node_title": custom, "node_label": where,
                             "class_type": class_type, "common": True, "schema": schema}, class_type, field))

    for slot in slots(api, kind, titles):
        _, custom, where = node_facts(slot["node"])
        name = slot_name({**slot, "label": where})
        zh, en = labels.ROLE_NAMES.get(slot["role"], ("素材", "Input"))
        found.append({"key": f"{slot['node']}.{slot['field']}", "node": slot["node"], "input": slot["field"],
                      "kind": "media", "role": slot["role"], "media": slot["media"],
                      "title": _pair(f"{zh} · {name['zh']}", f"{en} · {name['en']}"),
                      "node_title": custom, "node_label": where, "class_type": slot["class_type"], "common": True})

    if seed_inputs(api) or "seed" in placeholders:
        found.append({"key": "seed", "node": "", "input": "seed", "kind": "seed", "title": _pair("种子", "Seed"),
                      "node_title": "", "class_type": "", "common": True, "schema": {"type": "integer", "minimum": 0}})
    sized = size_node(api)
    if sized is not None or {"width", "height"} & placeholders:
        found.append({"key": "size", "node": "", "input": "size", "kind": "size", "title": _pair("尺寸", "Size"),
                      "node_title": "", "class_type": "", "common": True, "schema": _size_spec(api, sized)})
    if counts_runs(api):
        found.append({"key": "runs", "node": "", "input": "runs", "kind": "runs", "title": _pair("跑几遍", "Runs"),
                      "node_title": "", "class_type": "", "common": True,
                      "schema": _runs_spec(api, generation_nodes(api, kind, object_info, titles))})

    for described, spec, name in _tunable_entries(api, object_info, titles):
        item: dict[str, Any] = {"key": described.key, "node": described.node, "input": described.input,
                                "kind": _value_kind(spec), "title": name, "node_title": described.node_title,
                                "node_label": described.node_label, "class_type": described.class_type,
                                "common": "x-advanced" not in spec, "schema": spec}
        if described.hint:
            item["hint"] = described.hint
        if spec.get("x-model-folder"):
            item["folder"] = spec["x-model-folder"]
        found.append(item)
    return found


@dataclass(frozen=True)
class Field:
    """表单上的一项:一条能填的项(`items` 交回的),加上作者给它的说法(应用表单,ADR 0038 §2)。"""

    item: dict[str, Any]
    #: 作者起的名字;空串 = 用这一项自己的名字
    label: str = ""
    #: 文字项写成宿主的提示词 / 反向提示词(缺省表单里认出来的提示词格都是)
    main: bool = False
    #: 只许从这几项里挑(下拉、选模型文件的项);None = 不收窄
    choices: tuple[str, ...] | None = None

    @property
    def key(self) -> str:
        return str(self.item["key"])

    @property
    def kind(self) -> str:
        return str(self.item["kind"])

    @property
    def title(self) -> Any:
        return self.label or self.item["title"]


@dataclass(frozen=True)
class Form:
    """一张图的表单:生成目录、工具入参、跑的时候写哪几格,说的都是它。

    没有应用表单时是**缺省的应用**(`default_form`:全部能填的项,认出来的提示词格写提示词);有的话是作者挑的那几项,
    按作者排的顺序(见 app_form.resolve)。没挑的项照工作流原样跑:不进表单,也不被写。
    """

    fields: tuple[Field, ...]
    #: 作者挑过(工作流里有应用表单);False = 全自动推出来的缺省
    app: bool = False
    title: str = ""
    description: str = ""
    #: 标成「结果」的输出节点(「以后只要这张」,ADR 0038 §5):「结果取自」的缺省就是它们
    results: frozenset[str] = frozenset()

    def prompts(self) -> dict[tuple[str, str], str]:
        """写提示词的那几格(主提示词):`(节点, 输入名)` → prompt / negative。"""
        return {(one.item["node"], one.item["input"]): "negative" if one.item.get("role") == "negative" else "prompt"
                for one in self.fields if one.kind == "text" and one.main}

    def graph_item(self, kind: str) -> Field | None:
        return next((one for one in self.fields if one.kind == kind), None)

    def media(self) -> list[Field]:
        return [one for one in self.fields if one.kind == "media"]

    def parameters(self) -> list[Field]:
        """进参数表的那几项(`<节点 id>.<输入名>`),按表单的顺序。"""
        return [one for one in self.fields if one.kind in VALUE_KINDS and not (one.kind == "text" and one.main)]

    def slots(self) -> list[dict[str, str]]:
        """读素材的槽位(和 `slots` 同形),按表单的顺序 —— 宿主给的第 i 份接到这个角色的第 i 个槽位上。"""
        return [{"node": one.item["node"], "class_type": one.item["class_type"],
                 "title": one.item.get("node_title") or one.item["class_type"],
                 **({"label": one.item["node_label"]} if one.item.get("node_label") else {}), "media": one.item["media"],
                 "field": one.item["input"], "role": one.item["role"]} for one in self.media()]

    def slot_labels(self) -> dict[str, list[Any]]:
        """每个角色的槽位按顺序叫什么(宿主描述符的 `source_labels`;作者起的名字是一句,节点名按语言分)。

        应用表单里每个槽位都有名字(作者起的,没起就是节点名);缺省的表单只在名字说得出东西时才给 —— 一个角色有几个
        槽位、或者用户给读图节点起过名字(`YZ金鱼` 那种十个读图节点),免得给唯一的一格挂一个「加载图像 #10」。
        """
        named: dict[str, list[Any]] = {}
        for one, slot in zip(self.media(), self.slots(), strict=True):
            named.setdefault(slot["role"], []).append(one.label or plain(slot_name(slot)))
        if self.app:
            return named
        counts: dict[str, int] = {}
        custom: set[str] = set()
        for one in self.media():
            counts[one.item["role"]] = counts.get(one.item["role"], 0) + 1
            if one.item.get("node_title"):
                custom.add(one.item["role"])
        return {role: names for role, names in named.items() if counts[role] > 1 or role in custom}


def default_form(found: list[dict[str, Any]]) -> Form:
    """缺省的应用:全部能填的项,认出来的提示词格写宿主的提示词 / 反向提示词。"""
    return Form(tuple(Field(item, main=item["kind"] == "text" and bool(item.get("role"))) for item in found))


#: 「结果取自」那一项的参数键:不带点(带点的是 `<节点 id>.<输入名>`,见 run.overrides_from),选中的是节点 id。
OUTPUT_CHOICE = "output_node"
#: 「全部」:这一种里交回的每个节点各一份。
ALL_OUTPUTS = "all"
#: 「最终结果」:几个预览节点里有的只是中间一步或辅助图时(见 final_outputs)的缺省 —— 只交回最终的那几个。
#: 是一个固定的值、不是节点 id:工作流在 ComfyUI 里改过、节点号变了,它照样指着「最终结果」。
FINAL_OUTPUTS = "final"


def _node_label(node: dict[str, Any]) -> dict[str, str]:
    return node.get("label") or {"zh": node["title"], "en": node["title"]}


def _choice_name(node: dict[str, Any], nodes: list[dict[str, Any]]) -> dict[str, str]:
    """一个节点在「结果取自」里叫什么(`{"zh", "en"}`):节点给人看的名字(用户起的标题,没起就是 ComfyUI 给这类节点的名字,
    见 labels.node_name);几个节点同名(没改标题,都叫「保存图像」「预览图像」)才带上节点号。"""
    name = _node_label(node)
    same = sum(1 for one in nodes if _node_label(one) == name)
    return {lang: f"{name[lang]} #{node['node']}" for lang in ("zh", "en")} if same > 1 else dict(name)


#: 不是最终结果的那几个选项名后面标什么(见 final_outputs、auxiliary_view)。
_NOT_FINAL_MARKS = {"control": ("控制图", "control image"), "mask": ("蒙版", "mask"),
                    "": ("中间一步", "intermediate")}


def _output_choice(nodes: list[dict[str, str]], api: dict[str, Any],
                   object_info: dict[str, Any] | None = None, marked: frozenset[str] = frozenset()) -> dict[str, Any]:
    """「结果取自」:这一种的几个保存节点(一个都没存时是几个预览节点)各是一个选项,名字用节点标题。

    缺省是「最终结果」:几个预览节点里有的只是中间一步或控制图、蒙版(见 final_outputs)时,只交回最终的那几个,
    选项名里写明是哪个;别的那几个标着「中间一步」「控制图」「蒙版」。没有这种节点(几个保存节点,或几个互不相干的
    预览)时缺省「全部」。**用户标过结果**(`marked`,应用表单里的「以后只要这张」)时缺省是标了的那几个,
    选项名「你选的结果(节点名)」—— 不再猜。

    每个选项跑一遍交回几张写在 `x-outputs-per-run` 上(每个节点收到的批量,见 images_per_run):宿主据此按选中的那一项、
    乘上跑几遍摆占位。
    """
    saved = any(persists(api.get(node["node"]) or {}) for node in nodes)
    count = len(nodes)
    what = ("保存节点", "save nodes") if saved else ("预览节点", "preview nodes")
    finals = final_outputs(api, nodes, object_info, marked)
    final_ids = {node["node"] for node in finals}
    chosen = bool(final_ids & marked)
    staged = count - len(finals)
    labels: dict[str, Any] = {}
    enum: list[str] = []
    if staged:
        head = ("你选的结果", "Your result") if chosen else ("最终结果", "Final result")
        if len(finals) == 1:
            name = _choice_name(finals[0], nodes)
            labels[FINAL_OUTPUTS] = {"zh": f"{head[0]}({name['zh']})", "en": f"{head[1]} ({name['en']})"}
        else:
            labels[FINAL_OUTPUTS] = {"zh": f"{head[0]}({len(finals)} 个{what[0]})",
                                     "en": f"{head[1]}s ({len(finals)} {what[1]})"}
        enum.append(FINAL_OUTPUTS)
    labels[ALL_OUTPUTS] = {"zh": f"全部({count} 个{what[0]})", "en": f"All ({count} {what[1]})"}
    enum.append(ALL_OUTPUTS)
    for node in nodes:
        name = _choice_name(node, nodes)
        if node["node"] in final_ids or chosen:
            labels[node["node"]] = plain(name)
        else:
            zh, en = _NOT_FINAL_MARKS[auxiliary_view(api, node["node"], object_info)]
            labels[node["node"]] = {"zh": f"{name['zh']}({zh})", "en": f"{name['en']} ({en})"}
        enum.append(node["node"])
    if staged and chosen:
        description = {
            "zh": f"这张工作流有 {count} 个{what[0]},其中 {len(finals)} 个标成了它的结果(工作流库的「应用」里标的),缺省只交回"
                  f"它们。要每个都交回就选「全部」;只要其中一个就选它,别的{what[0]}不跑。",
            "en": f"This workflow has {count} {what[1]}, and only the one(s) marked as its result (in the workflow "
                  "library's App tab) come back by default. Pick All to get every one, or pick one to get only that one; "
                  f"the other {what[1]} don't run.",
        }
    elif staged:
        description = {
            "zh": f"这张工作流有 {count} 个{what[0]},其中 {staged} 个不是最终结果(接着被拿去再加工的那张、ControlNet 的"
                  f"控制图、蒙版),缺省只交回最终结果。要每个都交回就选「全部」;只要其中一个就选它,别的{what[0]}不跑。",
            "en": f"This workflow has {count} {what[1]}, and {staged} of them are not the final result (an image that "
                  "gets worked on further, a ControlNet control image, a mask), so only the final result comes back "
                  f"by default. Pick All to get every one, or pick one to get only that one; the other {what[1]} "
                  "don't run.",
        }
    else:
        description = {
            "zh": f"这张工作流有 {count} 个{what[0]},一次运行各交回一份;只要其中一个的就选它,别的{what[0]}不跑。",
            "en": f"This workflow has {count} {what[1]}, and each returns its own result per run. Pick one to get only "
                  f"that one; the other {what[1]} don't run.",
        }
    return {
        "type": "string",
        "title": {"zh": "结果取自", "en": "Results from"},
        "description": description,
        "enum": enum,
        "default": FINAL_OUTPUTS if staged else ALL_OUTPUTS,
        "x-enum-labels": labels,
        "x-outputs-per-run": {**({FINAL_OUTPUTS: images_per_run(api, finals)} if staged else {}),
                              ALL_OUTPUTS: images_per_run(api, nodes),
                              **{node["node"]: images_per_run(api, [node]) for node in nodes}},
    }


def chosen_outputs(api: dict[str, Any], kind: str, choice: str, object_info: dict[str, Any] | None = None,
                   titles: dict[str, str] | None = None, locale: str = "zh",
                   marked: frozenset[str] = frozenset()) -> set[str] | None:
    """「结果取自」选的那一项 → 这次交回哪几个输出节点的;None 是这一种交回的全部。

    **没选和选了缺省是同一件事**:宿主只发用户动过的参数(AI 工作台、智能体、工作流节点常常不带这一项),目录里
    `outputs_per_run` 说的是缺省那一项的份数 —— 跑的时候按同一个判据(final_outputs,标过结果的听标记)再判一遍,
    摆的占位和交回的份数才对得上。选的节点已经不在了(工作流在 ComfyUI 里改过)就说清楚。
    """
    delivering = generation_nodes(api, kind, object_info, titles)
    if choice == ALL_OUTPUTS:
        return None
    if choice and choice != FINAL_OUTPUTS:
        if choice not in {node["node"] for node in delivering}:
            from lines import ComfyError, say

            raise ComfyError(say(locale, f"「结果取自」选的节点 #{choice} 已经不在这张工作流里了 —— 到插件页点「刷新模型」再选一次",
                                 f"The node #{choice} picked in “Results from” is no longer in this workflow. "
                                 "Click Refresh models on the Plugins page and pick again."))
        return {choice}
    finals = final_outputs(api, delivering, object_info, marked)
    return {node["node"] for node in finals} if len(finals) < len(delivering) else None


def keep_outputs(api: dict[str, Any], kind: str, wanted: set[str], object_info: dict[str, Any] | None = None,
                 titles: dict[str, str] | None = None) -> dict[str, Any]:
    """只要 `wanted` 那几个节点交回的(见 chosen_outputs):这一种别的交回节点(没人接它的输出的)摘掉 —— ComfyUI
    只跑产出节点要的那些,放大那一路不要就不跑;中间一步的预览摘掉,它上游照样为最终结果跑。返回新图,不改入参。"""
    used = _consumers(api)
    graph = copy.deepcopy(api)
    for node in generation_nodes(api, kind, object_info, titles):
        if node["node"] not in wanted and not used.get(node["node"]):
            graph.pop(node["node"], None)
    return graph


def describe(
    model_id: str,
    label: Any,
    api: dict[str, Any],
    object_info: dict[str, Any],
    titles: dict[str, str] | None = None,
    form: Form | None = None,
) -> dict[str, Any]:
    """一张 API 图 → 插件目录里的一个模型(见 docs/PLUGIN_MANIFEST 的「替宿主做生成」)。

    说的是这张图的表单(`form`):有应用表单就是作者挑的那几项(见 app_form.resolve),没有就是缺省的应用 —— 全部能填的项
    (`default_form(items(…))`)。三处界面不认识「应用」,它们读的还是同一个描述符,只是短了:

    - 主提示词 / 反向提示词、种子、尺寸、跑几遍对到宿主自己的控件上(`negative_prompt` / `seed` / `size` /
      `num_images`,它在这里是跑几遍 —— `x-count-unit: runs`,见 counts_runs);
    - 其余的项按 `<节点 id>.<输入名>` 列成参数,按表单的顺序、用表单上的名字(缺省按常用程度,见 `tunable`);
    - 读素材的节点列成输入槽位(图、蒙版、首尾帧、视频、音频),每个槽位按顺序带名字(`labels`,见 Form.slot_labels);
    - 粘贴的模板里的 `{{占位符}}` 一样认(模板没有应用表单);
    - 提示词要不要写(`prompt`)从图里读:没有文字喂进采样器的(放大、抠图)是 `none`(见 prompt_requirement);应用表单里
      没有主提示词的也是 `none` —— 那几格照工作流里存的那句跑;
    - 跑一遍交回几张(`outputs_per_run`,「结果取自」按缺省时)照实说:这一种里交回的节点(见 generation_nodes)各按
      它收到的批量算(见 images_per_run),中间一步、控制图、蒙版这类预览不算、标过结果的只算标了的(见 final_outputs);
      不止一个时给一项「结果取自」(见 `_output_choice`)。宿主据此按跑几遍 × 一遍几张一次摆好那么多格占位。
    """
    titles = titles or {}
    kind = kind_of(api)
    sized = size_node(api)
    placeholders = _placeholders_in(api)
    form = form or default_form(items(api, object_info, titles))
    #: 占位符只在内置图和粘贴的模板里有,它们没有应用表单
    auto = set() if form.app else placeholders
    prompts = form.prompts()
    found_slots = form.slots()

    parameters: dict[str, dict[str, Any]] = {}
    if "negative" in prompts.values() or "negative" in auto:
        parameters["negative_prompt"] = {"type": "string"}
    if form.graph_item("seed"):
        parameters["seed"] = dict(form.graph_item("seed").item["schema"])  # type: ignore[union-attr]
    if form.graph_item("size"):
        parameters["size"] = dict(form.graph_item("size").item["schema"])  # type: ignore[union-attr]
    #: 跑一遍交回几张:缺省(最终结果,见 final_outputs)交回的那几个节点,各按它收到的批量(见 images_per_run);
    #: 「全部」时是这一种交回的每个节点 —— 再乘上最多跑几遍,是一次最多交回几张。
    delivering = generation_nodes(api, kind, object_info, titles)
    finals = final_outputs(api, delivering, object_info, form.results)
    per_run = max(1, images_per_run(api, finals))
    max_outputs = max(1, images_per_run(api, delivering))
    if form.graph_item("runs"):
        # 「张数」是跑几遍(见 run.generate):每遍按工作流原样,换一个种子;缺省跑一遍。宿主的「N×」是跑几遍 × 一遍几张。
        max_outputs *= MAX_RUNS
        parameters["num_images"] = dict(form.graph_item("runs").item["schema"])  # type: ignore[union-attr]
    if "steps" in auto:
        parameters["steps"] = {"type": "integer", "minimum": 1, "maximum": 200, "default": 20,
                               "title": {"zh": "步数", "en": "Steps"}}
    if "duration_seconds" in auto:
        parameters["duration_seconds"] = {"type": "integer", "minimum": 1}
    if len(delivering) > 1:
        parameters[OUTPUT_CHOICE] = _output_choice(delivering, api, object_info, form.results)
    for field in form.parameters():
        spec = dict(field.item["schema"])
        if field.choices is not None:
            spec["enum"] = list(field.choices)
        if form.app:
            spec.pop("x-advanced", None)  # 作者挑出来的每一项都摆在第一屏
        parameters[field.key] = {"title": field.title, **spec}

    counts: dict[str, int] = {}
    for slot in found_slots:
        counts[slot["role"]] = counts.get(slot["role"], 0) + 1
    if alpha_masks(api, found_slots):
        # 局部重绘拿 alpha 当蒙版:收一份蒙版(白色是要改的地方),替掉 alpha 那一路。不给就用图自己的 alpha。
        counts["mask"] = 1
    named = form.slot_labels()
    #: 图有没有提示词(判「处理一张图」的工作流)看整张图;表单收不收提示词看主提示词
    prompted = bool(text_slots(api, object_info)) or "prompt" in placeholders
    asks_prompt = bool(prompts) or "prompt" in auto
    image_roles = ("reference_image", "first_frame", "last_frame")
    # 没有提示词、也没有自己的画布(放大、抠图、修脸这类「处理一张图」的工作流):那张图是必须给的 ——
    # 否则 ComfyUI 会拿工作流里存着的那张示例图跑一遍,用户拿回来的不是自己的图。
    needs_image = not prompted or (sized is None and kind == "image")
    inputs: list[dict[str, Any]] = []
    first_image_marked = False
    for role, count in counts.items():
        entry: dict[str, Any] = {"role": role, "max": count}
        if named.get(role):
            entry["labels"] = named[role]
        if needs_image and role in image_roles and not first_image_marked:
            entry["required"] = True
            first_image_marked = True
        if role == "first_frame":
            # 图生视频:首帧接在生成节点上,不给的话 ComfyUI 拿工作流里存着的那张图生成一段(模式里也没有文生视频)
            entry["required"] = True
        if role in ("mask", "source_video") and role in {slot["role"] for slot in found_slots}:
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
            modes = ["text-to-video"] + (
                ["reference-to-video"] if "reference_image" in counts or "reference_video" in counts else [])
    elif kind == "audio":
        # 音乐 / 音效 / 配音(ADR 0022):宿主的音频模式里通用的那一个
        modes = ["text-to-audio"]
    else:
        has_image = any(role in counts for role in image_roles) or "mask" in counts
        modes = (["text-to-image"] if asks_prompt and not needs_image else []) + (["image-to-image"] if has_image else [])
        modes = modes or ["text-to-image"]

    model: dict[str, Any] = {
        "id": model_id,
        # 应用的标题换掉模型下拉里那一项的名字;模型 id 仍是文件路径
        "label": form.title if form.app and form.title else label,
        "kind": kind,
        "modes": modes,
        "parameters": parameters,
        "inputs": inputs,
        "max_outputs": max_outputs,
        "outputs_per_run": per_run,
        # 提示词要不要写:从图里读(见 prompt_requirement)。放大这类图是 none —— 宿主不再逼人敲一句没用的话。
        "prompt": prompt_requirement(api, prompts, auto),
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


def fill(api: dict[str, Any], values: dict[str, Any], overrides: dict[str, Any],
         object_info: dict[str, Any] | None = None,
         prompts: dict[tuple[str, str], str] | None = None) -> dict[str, Any]:
    """把一次请求写进 API 图(返回新图,不改入参)。

    `values`:提示词 / 反向 / 种子 / 宽高 —— 宿主的主控件。**只写给了的**:用户没选尺寸,这张图就用它自己的尺寸,
    而不是被一个默认的 1024 盖掉。画布上存着的 batch_size 不动:「张数」是跑几遍(见 counts_runs)。
    `overrides`:`<节点 id>.<输入名>` → 值,用户在参数表里动过的那些。只改字面量输入;节点或输入
    已经不在了就跳过(工作流可能在 ComfyUI 里改过了,不该为此报错)。
    `prompts`:提示词写进哪几格(表单的主提示词,见 Form.prompts);不给就是认出来的每一格(见 text_slots,
    `object_info` 和描述这张图时给的是同一份)—— 目录说「收提示词」的图,写进去的就是那几格。有应用表单时没标
    主提示词的那几格保留工作流里存的那句。
    """
    graph = copy.deepcopy(api)
    targets = text_slots(graph, object_info) if prompts is None else prompts
    for (node_id, name), role in targets.items():
        text = values.get(role)
        if text is not None and name in ((graph.get(node_id) or {}).get("inputs") or {}):
            graph[node_id]["inputs"][name] = text
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
    for key, value in (overrides or {}).items():
        node_id, dot, name = str(key).partition(".")
        if not dot:
            continue
        node = graph.get(node_id)
        if isinstance(node, dict) and name in (node.get("inputs") or {}) and _literal(node["inputs"][name]):
            node["inputs"][name] = value
    return substitute_placeholders(graph, {key: value for key, value in values.items() if value is not None})


def wire_inputs(api: dict[str, Any], kind: str, uploaded: dict[str, list[str]],
                found: list[dict[str, str]] | None = None) -> dict[str, Any]:
    """把传上去的素材接到读素材的节点上:每个角色的第 i 份给这个角色的第 i 个槽位。

    槽位是表单上的那几个、按表单的顺序(`found`,见 Form.slots);不给就是图里每一个读素材的节点,按节点顺序。
    给得比槽位少,剩下的槽位用它原来那份;给得比槽位多,多的不接(宿主按槽位数限过了)。

    **蒙版没有自己的槽位**时(局部重绘图常见的做法:LoadImage 的 alpha 就是蒙版,用户在 ComfyUI 的
    蒙版编辑器里画),给的蒙版另起一个 LoadImageMask,把原来接在 alpha 那一路上的下游改接过去 ——
    否则单独给的蒙版无处可去,重绘的还是工作流里存着的那一块。
    """
    graph = copy.deepcopy(api)
    used: dict[str, int] = {}
    found = slots(graph, kind) if found is None else [slot for slot in found if slot["node"] in graph]
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


def collect_outputs(history_entry: dict[str, Any], kind: str, nodes: set[str] | None = None) -> list[dict[str, Any]]:
    """一次**生成**要交回的文件:这次要的那一种(图 / 视频 / 音频),全部;`nodes`(「结果取自」选了一个)只要那几个
    节点的。每一项和 `all_outputs` 同形(`{node, class_type, item, media}`):交回时记下它来自哪个节点(`source_node`)。

    存下来的优先;一个都没有才用预览 —— 只接了 PreviewImage 的图也能出东西。视频图里常常同时有逐帧的图
    和合成的视频:要的是视频那几份,不是第一帧。跑之前在图上判的是 `generation_nodes`(同一个判据):
    目录里说的一次交回几份(`outputs_per_run`)、工具说「我和这个生成模型是同一件事」都是按它说的。
    """
    files, _ = all_outputs(history_entry, include_previews=True)
    wanted = [one for one in files if one["media"] == kind and (nodes is None or one["node"] in nodes)]
    # 这一种里存下来的优先;一份都没存(VHS 关了 save_output)才用预览 —— 不拿别的种类顶替
    saved = [one for one in wanted if one["item"].get("type") != "temp"]
    if saved or wanted:
        return saved or wanted
    if nodes is not None:
        return []  # 选中的节点什么都没交出:不拿别的节点顶替
    # 认不出种类(没有后缀的文件名之类):照旧交回第一份,总比说「没有产出」强
    fallback = [one for one in files if one["item"].get("type") != "temp"] or files
    return fallback[:1]


def interrupted(status: dict[str, Any]) -> bool:
    """这个任务是被中断的(ComfyUI 界面上点了中断、别人 /interrupt 了它),不是跑出了错。"""
    return any(isinstance(message, list) and message and message[0] == "execution_interrupted"
               for message in status.get("messages") or [])


def execution_error_parts(status: dict[str, Any]) -> tuple[str, str] | None:
    """ComfyUI 自己说的失败:(哪一类节点, 它的原话);历史里没有 execution_error 就是 None。"""
    for message in reversed(status.get("messages") or []):
        if isinstance(message, list) and len(message) == 2 and message[0] == "execution_error":
            payload = message[1] or {}
            return str(payload.get("node_type") or ""), str(payload.get("exception_message") or "")
    return None


def execution_error(status: dict[str, Any]) -> str:
    """ComfyUI 自己说的失败原因;一句都没有就是空串。"""
    parts = execution_error_parts(status)
    if parts is None:
        return ""
    node, said = parts
    return f"{node}: {said}".strip(": ") if said or node else "execution_error"


def checkpoint_files(api: dict[str, Any]) -> list[str]:
    """图里用 checkpoint 加载节点读的是哪几个模型文件(`ckpt_name`),按出现先后、不重复。"""
    found: list[str] = []
    for node in (api or {}).values():
        name = ((node or {}).get("inputs") or {}).get("ckpt_name") if isinstance(node, dict) else None
        if isinstance(name, str) and name.strip() and name not in found:
            found.append(name)
    return found


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
