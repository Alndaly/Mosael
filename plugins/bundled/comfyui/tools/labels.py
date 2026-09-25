"""工作流里一个可调输入**在 Mosael 里叫什么**、排第几、收不收进「高级」、给不给人调。

参数表是给人看的:`KSampler · sampler_name` 是 ComfyUI 的内部名字,放进一个 360px 宽的弹层,两列排版
下会折成两行、把控件挤出格子。所以常见的输入给一个**人话名字**(中英各一份,宿主按看的人的语言挑),
节点类名只在**需要区分**时才出现(两个 KSampler → 「采样器 · 第 2 个 KSampler」,用户给节点起了名字就用
那个名字),而原始的「节点 · 输入名」放进说明里,悬停看得到 —— 排错时要的正是它。

判据都在这一张表里:认得的输入有名字、有顺序、有「是不是常用」;不认得的(自定义节点的输入)照旧列出,
名字退回「节点标题 · 输入名」并收进「高级」—— 不认得不等于不让调。
"""

from __future__ import annotations

from dataclasses import dataclass


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


def _humanize(name: str) -> str:
    words = name.replace("_", " ").strip()
    return words[:1].upper() + words[1:] if words else name


def _custom_title(title: str, class_type: str) -> str:
    """用户给节点起的名字;没起(标题就是类名)回空串。"""
    title = (title or "").strip()
    return "" if not title or title == class_type else title


#: 同一个输入名在个别节点上是另一件事:UpscaleModelLoader 的 `model_name` 是放大模型,不是主模型。
KNOWN_BY_CLASS: dict[tuple[str, str], Known] = {
    ("UpscaleModelLoader", "model_name"): Known("放大模型", "Upscale model", 13, True),
    ("ControlNetApply", "strength"): Known("ControlNet 强度", "ControlNet strength", 26, True),
    ("ControlNetApplyAdvanced", "strength"): Known("ControlNet 强度", "ControlNet strength", 26, True),
}


def describe(node: str, name: str, class_type: str, title: str, order: int) -> Parameter:
    known = KNOWN_BY_CLASS.get((class_type, name)) or KNOWN.get(name)
    custom = _custom_title(title, class_type)
    if known is None:
        # 不认得的输入:名字里带上它是哪个节点的,否则两个自定义节点的 `strength` 分不清
        where = custom or class_type
        return Parameter(
            key=f"{node}.{name}", node=node, input=name, class_type=class_type, node_title=custom,
            rank=1000 + order, common=False, zh=f"{where} · {_humanize(name)}", en=f"{where} · {_humanize(name)}",
        )
    return Parameter(
        key=f"{node}.{name}", node=node, input=name, class_type=class_type, node_title=custom,
        rank=known.rank * 1000 + order, common=known.common, zh=known.zh, en=known.en,
    )


def titled(parameters: list[Parameter]) -> dict[str, dict[str, str]]:
    """每个参数最终的名字(`{"zh", "en"}`)。**只在撞名时**才带上是哪个节点。

    - 用户给节点起了名字 → 「采样器 · 精修」;
    - 没起名字 → 同一类节点里按出现顺序数,第一个不带尾巴,之后的「采样器 · 第 2 个 KSampler」;
    - 不撞名 → 就是「采样器」,不带任何技术名词。
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
            if one.node_title:
                hint_zh = hint_en = one.node_title
            elif position == 0:
                out[one.key] = {"zh": one.zh, "en": one.en}
                continue
            elif classes.count(one.class_type) > 1:
                index = per_class[one.class_type]
                hint_zh, hint_en = f"第 {index} 个 {one.class_type}", f"{one.class_type} #{index}"
            else:
                hint_zh = hint_en = one.class_type
            out[one.key] = {"zh": f"{one.zh} · {hint_zh}", "en": f"{one.en} · {hint_en}"}
    return out


__all__ = ["HIDDEN_INPUTS", "KNOWN", "Known", "Parameter", "describe", "titled"]
