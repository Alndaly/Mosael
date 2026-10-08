"""工作流里一个可调输入**在 Mosael 里叫什么**、排第几、收不收进「高级」、给不给人调。

参数表是给人看的:`KSampler · sampler_name` 是 ComfyUI 的内部名字,放进一个 360px 宽的弹层,两列排版
下会折成两行、把控件挤出格子。所以常见的输入给一个**人话名字**(中英各一份,宿主按看的人的语言挑),
节点类名只在**需要区分**时才出现(两个 KSampler → 「采样器 · 第 2 个 KSampler」,用户给节点起了名字就用
那个名字),而原始的「节点 · 输入名」放进说明里,悬停看得到 —— 排错时要的正是它。

判据都在这一张表里:认得的输入有名字、有顺序、有「是不是常用」;不认得的(自定义节点的输入)照旧列出,
名字退回「节点名 · 这一格的名字」并收进「高级」—— 不认得不等于不让调。

**节点叫什么**(`node_name`)不用类名:`LoraLoader|pysssss` 是 ComfyUI 内部的键,给人看的是用户起的标题,其次是
ComfyUI 自己给这类节点的名字 —— `/i18n` 里按语言的翻译(自定义节点包带的 locales),再是 object_info 的 `display_name`
(「Lora Loader 🐍」)。ComfyUI 的接口不带核心节点的中文名(那在它的前端包里),常见的几十个核心节点在 `CORE_NODE_ZH`
里给一份。一格输入不认得时,名字用 ComfyUI 给这一格起的名字(`/i18n` 的、object_info 里的 `display_name`),它的说明
(`tooltip`)交给界面当悬停说明。ComfyUI 标了 `hidden` 的输入(pysssss 的 LoRA 加载器存示例提示词的那一格)界面上本来
就没有,不列;标了 `advanced` 的收进「高级」。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Known:
    zh: str
    en: str
    #: 排序:越小越靠前。常用的(选模型、步数、CFG、采样器)在前,细节在后。
    rank: int
    #: 常用的留在第一屏;其余「留空也能跑」的收进「高级」。
    common: bool = False


#: 输入名 → 名字。**不按节点类区分**:`steps` 在 KSampler、KSamplerAdvanced、BasicScheduler 上是同一件事。
KNOWN: dict[str, Known] = {
    # 选哪个模型:最先看的那一格
    "ckpt_name": Known("模型", "Checkpoint", 10, True),
    "unet_name": Known("扩散模型", "Diffusion model", 11, True),
    "model_name": Known("模型", "Model", 12, True),
    "lora_name": Known("LoRA", "LoRA", 20, True),
    "strength_model": Known("LoRA 强度", "LoRA strength", 21, True),
    "strength_clip": Known("LoRA 文本强度", "LoRA CLIP strength", 22),
    "control_net_name": Known("ControlNet 模型", "ControlNet model", 25, True),
    "strength": Known("强度", "Strength", 26, True),
    "vae_name": Known("VAE", "VAE", 30),
    "clip_name": Known("文本编码器", "Text encoder", 31),
    "clip_name1": Known("文本编码器 1", "Text encoder 1", 32),
    "clip_name2": Known("文本编码器 2", "Text encoder 2", 33),
    "clip_name3": Known("文本编码器 3", "Text encoder 3", 34),
    "weight_dtype": Known("权重精度", "Weight dtype", 35),
    # 采样
    "steps": Known("步数", "Steps", 40, True),
    "cfg": Known("CFG", "CFG", 41, True),
    "guidance": Known("引导强度", "Guidance", 42, True),
    "sampler_name": Known("采样器", "Sampler", 43, True),
    "scheduler": Known("调度器", "Scheduler", 44, True),
    "denoise": Known("降噪强度", "Denoise", 45, True),
    "shift": Known("偏移", "Shift", 46),
    "max_shift": Known("最大偏移", "Max shift", 47),
    "base_shift": Known("基础偏移", "Base shift", 48),
    "start_at_step": Known("起始步", "Start at step", 49),
    "end_at_step": Known("结束步", "End at step", 50),
    "add_noise": Known("加噪", "Add noise", 51),
    "return_with_leftover_noise": Known("保留剩余噪声", "Return with leftover noise", 52),
    "start_percent": Known("起始位置", "Start percent", 53),
    "end_percent": Known("结束位置", "End percent", 54),
    # 画面与视频
    "width": Known("宽度", "Width", 60),
    "height": Known("高度", "Height", 61),
    "length": Known("帧数", "Frames", 62, True),
    "frame_rate": Known("帧率", "Frame rate", 63, True),
    "fps": Known("帧率", "Frame rate", 63, True),
    "scale_by": Known("缩放倍数", "Scale factor", 64, True),
    "upscale_method": Known("缩放算法", "Upscale method", 65),
    "megapixels": Known("像素量(百万)", "Megapixels", 66),
    "crop": Known("裁切", "Crop", 67),
    "grow_mask_by": Known("蒙版外扩", "Grow mask by", 68),
    "format": Known("格式", "Format", 70),
    "crf": Known("质量(CRF)", "Quality (CRF)", 71),
    "loop_count": Known("循环次数", "Loop count", 72),
    "pingpong": Known("往返播放", "Ping-pong", 73),
    "codec": Known("编码", "Codec", 74),
}

#: 这些输入**不在 Mosael 里调**:文件名前缀、存不存元数据这类是 ComfyUI 那一侧的事,在一个生成弹层里
#: 摆出来只会让人以为它影响画面。LoadImage 的 `upload` 是界面上的上传按钮,不是一个值。
HIDDEN_INPUTS = frozenset(
    {"filename_prefix", "save_output", "save_metadata", "upload", "control_after_generate", "choose file to upload"}
)


#: 选**模型文件**的输入 → 它的文件在哪个模型目录(ComfyUI 的 folder_paths 名)。生成表单据此从模型库取缩略图、
#: 底模和触发词(ADR 0034 后续)。按输入名认;同名输入在不同节点上指不同目录的,写在 _MODEL_FOLDER_NODES 里。
#: 认不出就不写 —— 表单照旧是一个普通下拉。
_MODEL_FOLDER_INPUTS = {
    "ckpt_name": "checkpoints",
    "lora_name": "loras",
    "vae_name": "vae",
    "unet_name": "diffusion_models",
    "clip_name": "text_encoders",
    "clip_name1": "text_encoders",
    "clip_name2": "text_encoders",
    "clip_name3": "text_encoders",
    "clip_name4": "text_encoders",
    "control_net_name": "controlnet",
    "style_model_name": "style_models",
    "gligen_name": "gligen",
    "hypernetwork_name": "hypernetworks",
    "upscale_model": "upscale_models",
}
_MODEL_FOLDER_NODES = {
    ("CLIPVisionLoader", "clip_name"): "clip_vision",
    ("UpscaleModelLoader", "model_name"): "upscale_models",
    ("UnetLoaderGGUF", "unet_name"): "unet_gguf",
    ("CLIPLoaderGGUF", "clip_name"): "clip_gguf",
    ("DualCLIPLoaderGGUF", "clip_name1"): "clip_gguf",
    ("DualCLIPLoaderGGUF", "clip_name2"): "clip_gguf",
}


def model_folder(class_type: str, name: str) -> str:
    """这个输入选的是哪个模型目录的文件;不是选模型文件的输入回空串。"""
    return _MODEL_FOLDER_NODES.get((class_type, name)) or _MODEL_FOLDER_INPUTS.get(name, "")


#: 读素材的槽位按宿主的素材角色叫什么(能填的项的名字、应用表单编辑器里列的那一行,见 graph.items)。
ROLE_NAMES: dict[str, tuple[str, str]] = {
    "reference_image": ("参考图", "Reference image"),
    "first_frame": ("首帧", "First frame"),
    "last_frame": ("尾帧", "Last frame"),
    "mask": ("蒙版", "Mask"),
    "source_video": ("视频", "Video"),
    "reference_video": ("参考视频", "Reference video"),
    "driving_audio": ("驱动音频", "Driving audio"),
    "reference_audio": ("参考音频", "Reference audio"),
}


#: 常见核心节点的中文名。ComfyUI 的 `/i18n` 只带自定义节点包自己的翻译,核心节点的中文在它的前端包里、接口拿不到;
#: 英文用 object_info 的 `display_name`。不在表里的核心节点中文也退回英文名 —— 总比类名好认。
CORE_NODE_ZH: dict[str, str] = {
    "CheckpointLoaderSimple": "Checkpoint 加载器",
    "KSampler": "K 采样器",
    "KSamplerAdvanced": "K 采样器(高级)",
    "SamplerCustom": "自定义采样器",
    "SamplerCustomAdvanced": "自定义采样器(高级)",
    "KSamplerSelect": "采样器选择",
    "BasicScheduler": "基本调度器",
    "RandomNoise": "随机噪声",
    "CFGGuider": "CFG 引导器",
    "BasicGuider": "基本引导器",
    "CLIPTextEncode": "CLIP 文本编码",
    "CLIPSetLastLayer": "设置 CLIP 最后一层",
    "EmptyLatentImage": "空 Latent 图像",
    "EmptySD3LatentImage": "空 Latent 图像(SD3)",
    "VAEDecode": "VAE 解码",
    "VAEDecodeTiled": "VAE 分块解码",
    "VAEEncode": "VAE 编码",
    "VAELoader": "加载 VAE",
    "LoadImage": "加载图像",
    "LoadImageMask": "加载图像(作为蒙版)",
    "SaveImage": "保存图像",
    "PreviewImage": "预览图像",
    "LoraLoader": "加载 LoRA",
    "LoraLoaderModelOnly": "加载 LoRA(仅模型)",
    "UpscaleModelLoader": "加载放大模型",
    "ImageUpscaleWithModel": "用模型放大图像",
    "ImageScale": "缩放图像",
    "ImageScaleBy": "按比例缩放图像",
    "LatentUpscaleBy": "按比例缩放 Latent",
    "ControlNetLoader": "加载 ControlNet 模型",
    "ControlNetApply": "应用 ControlNet",
    "ControlNetApplyAdvanced": "应用 ControlNet(高级)",
    "UNETLoader": "UNet 加载器",
    "CLIPLoader": "加载 CLIP",
    "DualCLIPLoader": "双 CLIP 加载器",
    "CLIPVisionLoader": "加载 CLIP 视觉模型",
    "StyleModelLoader": "加载风格模型",
    "FluxGuidance": "Flux 引导",
    "ModelSamplingFlux": "采样算法(Flux)",
    "ModelSamplingSD3": "采样算法(SD3)",
    "InpaintModelConditioning": "局部重绘条件",
    "SetLatentNoiseMask": "设置 Latent 噪声蒙版",
    "WanImageToVideo": "图生视频(Wan)",
    "LoadVideo": "加载视频",
    "SaveVideo": "保存视频",
    "LoadAudio": "加载音频",
    "SaveAudio": "保存音频",
    "PreviewAudio": "预览音频",
    "SaveAnimatedWEBP": "保存动画(WEBP)",
    "PrimitiveString": "字符串",
    "PrimitiveStringMultiline": "字符串(多行)",
    "PrimitiveInt": "整数",
    "PrimitiveFloat": "浮点数",
    "PrimitiveBoolean": "开关",
}

#: object_info 里每类节点上,Mosael 并进去的那一份「ComfyUI 给的各语言名字」(`/i18n` 的 nodeDefs,见
#: comfy_http.Comfy.object_info):`{"zh": {"display_name", "inputs": {名字: {"name", "tooltip"}}}, "en": {…}}`。
I18N_KEY = "mosael_i18n"
#: 并进去的语言:界面只有这两种。
LOCALES = ("zh", "en")


def with_i18n(object_info: dict[str, Any], translations: Any) -> dict[str, Any]:
    """object_info 并上 ComfyUI 的 `/i18n`(`{语言: {"nodeDefs": {类名: {...}}}}`):每类节点多一格 `I18N_KEY`,只留
    名字和说明这几样字。形状不对、没有这一类的就不并 —— 名字照旧从 object_info 的 `display_name` 来。"""
    if not isinstance(translations, dict):
        return object_info
    found: dict[str, dict[str, Any]] = {}
    for locale in LOCALES:
        defs = (translations.get(locale) or {}).get("nodeDefs") if isinstance(translations.get(locale), dict) else None
        if not isinstance(defs, dict):
            continue
        for class_type, one in defs.items():
            if class_type not in object_info or not isinstance(one, dict):
                continue
            entry: dict[str, Any] = {}
            if isinstance(one.get("display_name"), str) and one["display_name"].strip():
                entry["display_name"] = one["display_name"].strip()
            inputs = one.get("inputs") if isinstance(one.get("inputs"), dict) else {}
            named = {name: {key: value.strip() for key, value in spec.items()
                            if key in ("name", "tooltip") and isinstance(value, str) and value.strip()}
                     for name, spec in inputs.items() if isinstance(name, str) and isinstance(spec, dict)}
            if any(named.values()):
                entry["inputs"] = {name: spec for name, spec in named.items() if spec}
            if entry:
                found.setdefault(class_type, {})[locale] = entry
    if not found:
        return object_info
    return {class_type: ({**info, I18N_KEY: found[class_type]} if class_type in found and isinstance(info, dict) else info)
            for class_type, info in object_info.items()}


def _info(object_info: dict[str, Any] | None, class_type: str) -> dict[str, Any]:
    info = (object_info or {}).get(class_type)
    return info if isinstance(info, dict) else {}


def _translated(info: dict[str, Any], locale: str) -> dict[str, Any]:
    names = info.get(I18N_KEY)
    one = names.get(locale) if isinstance(names, dict) else None
    return one if isinstance(one, dict) else {}


def _custom_title(title: str, class_type: str) -> str:
    """用户给节点起的名字;没起(标题就是类名)回空串。"""
    title = (title or "").strip()
    return "" if not title or title == class_type else title


def node_name(class_type: str, title: str = "", object_info: dict[str, Any] | None = None) -> dict[str, str]:
    """一个节点给人看的名字(`{"zh", "en"}`):用户起的标题;没起就是 ComfyUI 给这类节点的名字 —— `/i18n` 里按语言的、
    核心节点的中文(CORE_NODE_ZH)、object_info 的 `display_name`;都没有才是类名。"""
    custom = _custom_title(title, class_type)
    if custom:
        return {"zh": custom, "en": custom}
    info = _info(object_info, class_type)
    shown = info.get("display_name").strip() if isinstance(info.get("display_name"), str) else ""
    en = _translated(info, "en").get("display_name") or shown or class_type
    zh = _translated(info, "zh").get("display_name") or CORE_NODE_ZH.get(class_type) or shown or class_type
    return {"zh": zh, "en": en}


def _input_options(info: dict[str, Any], name: str) -> dict[str, Any]:
    inputs = info.get("input") if isinstance(info.get("input"), dict) else {}
    for section in ("required", "optional"):
        group = inputs.get(section) if isinstance(inputs.get(section), dict) else {}
        spec = group.get(name)
        if isinstance(spec, list) and len(spec) > 1 and isinstance(spec[1], dict):
            return spec[1]
    return {}


def _input_text(object_info: dict[str, Any] | None, class_type: str, name: str, key: str,
                option: str) -> dict[str, str] | None:
    info = _info(object_info, class_type)
    own = _input_options(info, name).get(option)
    own = own.strip() if isinstance(own, str) else ""
    found = {}
    for locale in LOCALES:
        spec = (_translated(info, locale).get("inputs") or {}).get(name) or {}
        found[locale] = spec.get(key) or ""
    if not any(found.values()) and not own:
        return None
    # 一种语言没给就用另一种 / object_info 里的那一句
    fallback = own or found["en"] or found["zh"]
    return {locale: found[locale] or fallback for locale in LOCALES}


def input_name(class_type: str, name: str, object_info: dict[str, Any] | None = None) -> dict[str, str] | None:
    """ComfyUI 给这一格起的名字(`/i18n` 按语言的、object_info 里的 `display_name`);和输入名一样或没起是 None。"""
    found = _input_text(object_info, class_type, name, "name", "display_name")
    if found is None or all(value == name for value in found.values()):
        return None
    return found


def input_hint(class_type: str, name: str, object_info: dict[str, Any] | None = None) -> dict[str, str] | None:
    """ComfyUI 给这一格的说明(`tooltip`,按语言);没有是 None。"""
    return _input_text(object_info, class_type, name, "tooltip", "tooltip")


def hidden_input(class_type: str, name: str, object_info: dict[str, Any] | None = None) -> bool:
    """ComfyUI 标了 `hidden` 的输入:界面上本来就没有这一格(pysssss 的 LoRA 加载器存示例提示词的 `prompt`)。"""
    return _input_options(_info(object_info, class_type), name).get("hidden") is True


def advanced_input(class_type: str, name: str, object_info: dict[str, Any] | None = None) -> bool:
    """ComfyUI 标了 `advanced` 的输入(它自己的界面里收在「高级」里的那几格)。"""
    return _input_options(_info(object_info, class_type), name).get("advanced") is True


@dataclass(frozen=True)
class Parameter:
    """描述好的一个参数(还没挂到模型上)。"""

    key: str
    node: str
    input: str
    class_type: str
    node_title: str
    rank: int
    common: bool
    zh: str
    en: str
    #: 节点给人看的名字(`node_name`):撞名时带上它,而不是类名
    node_label: dict[str, str] = field(default_factory=dict)
    #: ComfyUI 给这一格的说明(按语言),没有是 None
    hint: dict[str, str] | None = None
    #: 名字里已经带着是哪个节点(不认得的输入是「节点名 · 这一格」):撞名时不再接一遍节点名
    names_node: bool = False


def _humanize(name: str) -> str:
    words = name.replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else name


#: 同一个输入名在个别节点上是另一件事:UpscaleModelLoader 的 `model_name` 是放大模型,不是主模型。
KNOWN_BY_CLASS: dict[tuple[str, str], Known] = {
    ("UpscaleModelLoader", "model_name"): Known("放大模型", "Upscale model", 13, True),
    ("ControlNetApply", "strength"): Known("ControlNet 强度", "ControlNet strength", 26, True),
    ("ControlNetApplyAdvanced", "strength"): Known("ControlNet 强度", "ControlNet strength", 26, True),
}


def describe(node: str, name: str, class_type: str, title: str, order: int,
             object_info: dict[str, Any] | None = None) -> Parameter:
    known = KNOWN_BY_CLASS.get((class_type, name)) or KNOWN.get(name)
    custom = _custom_title(title, class_type)
    where = node_name(class_type, title, object_info)
    hint = input_hint(class_type, name, object_info)
    #: ComfyUI 自己把这一格收在「高级」里:我们也收(常用表说它常用也一样 —— 那是它在别的节点上)
    advanced = advanced_input(class_type, name, object_info)
    if known is None:
        # 不认得的输入:名字里带上它是哪个节点的,否则两个自定义节点的 `strength` 分不清
        own = input_name(class_type, name, object_info) or {"zh": _humanize(name), "en": _humanize(name)}
        return Parameter(
            key=f"{node}.{name}", node=node, input=name, class_type=class_type, node_title=custom,
            rank=1000 + order, common=False, zh=f"{where['zh']} · {own['zh']}", en=f"{where['en']} · {own['en']}",
            node_label=where, hint=hint, names_node=True,
        )
    return Parameter(
        key=f"{node}.{name}", node=node, input=name, class_type=class_type, node_title=custom,
        rank=known.rank * 1000 + order, common=known.common and not advanced, zh=known.zh, en=known.en,
        node_label=where, hint=hint,
    )


def _ordinal(n: int) -> str:
    """英文的「第几个」(`2nd`):不写成 `#2` —— `#` 后面跟的是节点号(见 numbered),两种数混在一张表里分不清。"""
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def numbered(names: dict[str, dict[str, str]], nodes: dict[str, str]) -> dict[str, dict[str, str]]:
    """还是撞名的那几个(同一个标题的几个节点 —— 复制出来的那种):每个后面带上节点号(`#12`),和画布上节点角上的号对得上。
    `names`:键 → 名字(`{"zh", "en"}`);`nodes`:键 → 节点号(图级的项没有节点,不带)。哪种语言撞了都算撞。"""
    count: dict[tuple[str, str], int] = {}
    for name in names.values():
        for lang in ("zh", "en"):
            count[(lang, name[lang])] = count.get((lang, name[lang]), 0) + 1
    out: dict[str, dict[str, str]] = {}
    for key, name in names.items():
        clash = any(count[(lang, name[lang])] > 1 for lang in ("zh", "en"))
        out[key] = {lang: f"{name[lang]} #{nodes[key]}" for lang in ("zh", "en")} if clash and nodes.get(key) else name
    return out


def titled(parameters: list[Parameter]) -> dict[str, dict[str, str]]:
    """每个参数最终的名字(`{"zh", "en"}`)。**只在撞名时**才带上是哪个节点 —— 用节点给人看的名字(`node_name`),不用类名。

    - 用户给节点起了名字 → 「采样器 · 精修」;
    - 没起名字 → 同一类节点里按出现顺序数,第一个不带尾巴,之后的「采样器 · 第 2 个 K 采样器」;
    - 不撞名 → 就是「采样器」,不带任何技术名词;
    - 名字里本来就带着节点名的(不认得的输入)不再接一遍;这样还撞的(几个节点标题一样)各带上节点号,见 numbered。
    """
    seen: dict[str, list[Parameter]] = {}
    for one in parameters:
        seen.setdefault(one.zh, []).append(one)
    out: dict[str, dict[str, str]] = {}
    for group in seen.values():
        if len(group) == 1:
            one = group[0]
            out[one.key] = {"zh": one.zh, "en": one.en}
            continue
        classes = [one.class_type for one in group]
        per_class: dict[str, int] = {}
        for position, one in enumerate(group):
            per_class[one.class_type] = per_class.get(one.class_type, 0) + 1
            where = one.node_label or {"zh": one.class_type, "en": one.class_type}
            if one.names_node:
                out[one.key] = {"zh": one.zh, "en": one.en}
                continue
            if one.node_title:
                hint_zh = hint_en = one.node_title
            elif position == 0:
                out[one.key] = {"zh": one.zh, "en": one.en}
                continue
            elif classes.count(one.class_type) > 1:
                index = per_class[one.class_type]
                hint_zh, hint_en = f"第 {index} 个 {where['zh']}", f"{_ordinal(index)} {where['en']}"
            else:
                hint_zh, hint_en = where["zh"], where["en"]
            out[one.key] = {"zh": f"{one.zh} · {hint_zh}", "en": f"{one.en} · {hint_en}"}
    return numbered(out, {one.key: one.node for one in parameters})


__all__ = ["CORE_NODE_ZH", "HIDDEN_INPUTS", "I18N_KEY", "KNOWN", "Known", "Parameter", "ROLE_NAMES", "advanced_input",
           "describe", "hidden_input", "input_hint", "input_name", "node_name", "numbered", "titled", "with_i18n"]
