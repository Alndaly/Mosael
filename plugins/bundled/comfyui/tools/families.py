"""底模家族怎么认(ADR 0034 §2,规矩也写在插件 README 里):先看文件头里的元数据,再看文件名,认不出不猜。

模型库列表、Civitai / ModelScope 链接解析共用这一份。
"""

from __future__ import annotations

import re
from typing import Any

#: 按文件名猜家族的目录:放的是「给某个底模用的」东西。文本编码器、放大模型、检测模型这类不按名字猜 ——
#: 一个叫 qwen3vl_4b 的文本编码器不是 Qwen-Image。
NAME_INFERRED_FOLDERS = frozenset({
    "checkpoints", "loras", "lycoris", "diffusion_models", "unet", "unet_gguf", "controlnet", "embeddings",
    "hypernetworks", "vae", "model_patches", "style_models", "ipadapter",
})
#: 元数据里写的底模(`ss_base_model_version` / `modelspec.architecture`)→ 家族。按先后认,认到为止。
_META_FAMILIES: tuple[tuple[re.Pattern[str], str], ...] = tuple((re.compile(pattern), label) for pattern, label in (
    (r"kontext", "Flux Kontext"),
    (r"flux[-_.]?2", "Flux.2"),
    (r"flux", "Flux"),
    (r"chroma", "Chroma"),
    (r"minimax[-_]?h3", "MiniMax H3"),
    (r"qwen[-_]?image", "Qwen-Image"),
    (r"hidream", "HiDream"),
    # ModelScope 登记的底模类型写成 WAN_VIDEO_2_2_I2V_A_14_B
    (r"wan[-_. ]?(?:video[-_. ]?)?2[._]?2|wan22", "Wan 2.2"),
    (r"wan", "Wan 2.1"),
    (r"hunyuan", "HunyuanVideo"),
    (r"ltx", "LTX-Video"),
    (r"lumina", "Lumina"),
    (r"z[-_]?image", "Z-Image"),
    (r"sd3|stable-diffusion-3|sd_3", "SD 3"),
    (r"pony", "Pony"),
    (r"illustrious", "Illustrious"),
    (r"noob", "NoobAI"),
    (r"sdxl|stable-diffusion-xl|sd_xl", "SDXL"),
    # ModelScope 写成 SD_2 / SD_2_1
    (r"sd_?v?2|stable-diffusion-v2", "SD 2"),
    (r"sd_?v1|stable-diffusion-v1|sd_?1[._]?5|sd1", "SD 1.5"),
))
#: 文件名(连子目录)里的关键词 → 家族。SDXL 的几支(Illustrious、NoobAI、Pony)排在 SDXL 前面。
_NAME_FAMILIES: tuple[tuple[re.Pattern[str], str], ...] = tuple((re.compile(pattern), label) for pattern, label in (
    (r"illustrious|(?:^|[^a-z])il(?:xl)?(?:[^a-z]|$)", "Illustrious"),
    (r"noob", "NoobAI"),
    (r"pony|(?:^|[^a-z])pdxl", "Pony"),
    (r"kontext", "Flux Kontext"),
    (r"flux[-_. ]?2", "Flux.2"),
    (r"flux", "Flux"),
    (r"chroma", "Chroma"),
    (r"qwen[-_ ]?image", "Qwen-Image"),
    (r"hidream", "HiDream"),
    (r"wan[-_. ]?2[._]?2|wan22", "Wan 2.2"),
    (r"wan[-_. ]?2[._]?1|wan21", "Wan 2.1"),
    (r"hunyuan", "HunyuanVideo"),
    (r"ltx", "LTX-Video"),
    (r"z[-_ ]?image", "Z-Image"),
    (r"(?:^|[^a-z])sd[-_ ]?3", "SD 3"),
    (r"sdxl|sd_xl|(?:^|[^a-z])xl(?:[^a-z]|$)", "SDXL"),
    (r"sd[-_ ]?1[._]?5|v1[-_]5|sd15", "SD 1.5"),
))
#: 认出是 SDXL 之后,训练用的底模名 / 文件名里带这几个的,细分成那一支。
_SDXL_BRANCHES = ("Illustrious", "NoobAI", "Pony")


def _by_name(text: str, rules: tuple[tuple[re.Pattern[str], str], ...]) -> str:
    lowered = text.lower()
    return next((label for pattern, label in rules if pattern.search(lowered)), "")


def family_of(folder: str, name: str, meta: dict[str, Any]) -> tuple[str, str]:
    """推断的底模家族和凭的是什么(`metadata` / `filename`);认不出是 ("", "")。规矩写在插件 README 里:

    1. `ss_base_model_version`(kohya 训练脚本写的,最具体)—— 它说的是训练脚本认得的那几个之外的底模时(anima、krea2),
       `modelspec.architecture` 会照默认写成 stable-diffusion-v1,不能信后者;
    2. 没有它时看 `modelspec.architecture`(SAI 的模型规范);
    3. 认出是 SDXL 的,训练用的底模名 `ss_sd_model_name` 或文件名里带 illustrious / noob / pony 的,细分成那一支;
    4. 都没有时看文件名(连子目录)里的关键词 —— 只在放「给某个底模用的东西」的目录里猜;
    5. 元数据里写了、表里没有的值原样交出,不往认得的家族上靠。
    """
    stem = name.replace("\\", "/")
    for key in ("ss_base_model_version", "modelspec.architecture"):
        raw = meta.get(key)
        if not isinstance(raw, str) or not raw.strip():
            continue
        value = raw.strip().split("/")[0]
        label = _by_name(value, _META_FAMILIES)
        if label == "SDXL":
            hint = _by_name(f"{meta.get('ss_sd_model_name') or ''} {meta.get('modelspec.title') or ''}", _NAME_FAMILIES)
            if hint in _SDXL_BRANCHES:
                return hint, "metadata"
            from_name = _by_name(stem, _NAME_FAMILIES)
            if from_name in _SDXL_BRANCHES:
                return from_name, "filename"
        return (label or value[:80]), "metadata"
    if folder in NAME_INFERRED_FOLDERS:
        label = _by_name(stem, _NAME_FAMILIES)
        if label:
            return label, "filename"
    return "", ""


#: Civitai 的 `baseModel`(「SDXL 1.0」「Illustrious」「Flux.1 D」「Wan Video 2.2 T2V-A14B」……)→ 家族。
_BASE_FAMILIES: tuple[tuple[re.Pattern[str], str], ...] = tuple((re.compile(pattern), label) for pattern, label in (
    (r"kontext", "Flux Kontext"),
    (r"flux\.?2", "Flux.2"),
    (r"flux", "Flux"),
    (r"illustrious", "Illustrious"),
    (r"noob", "NoobAI"),
    (r"pony", "Pony"),
    (r"sdxl", "SDXL"),
    (r"sd ?3", "SD 3"),
    (r"sd ?2", "SD 2"),
    (r"sd ?1", "SD 1.5"),
    (r"wan(?: video)? ?2\.2", "Wan 2.2"),
    (r"wan", "Wan 2.1"),
    (r"hunyuan", "HunyuanVideo"),
    (r"ltx", "LTX-Video"),
    (r"qwen", "Qwen-Image"),
    (r"hidream", "HiDream"),
    (r"chroma", "Chroma"),
    (r"lumina", "Lumina"),
    (r"z[- ]?image", "Z-Image"),
))


def family_from_base(base: str) -> str:
    """Civitai 写的底模 → 家族;表里没有的原样交出(不往认得的家族上靠)。"""
    text = (base or "").strip()
    return _by_name(text, _BASE_FAMILIES) or text[:80] if text else ""


def family_from_modelscope(vision: str, bases: list[str], own: tuple[str, ...] = ()) -> str:
    """ModelScope AIGC 专区登记的底模 → 家族。`VisionFoundation` 是它的底模类型(SD_XL、FLUX_1、QWEN_IMAGE_20_B、
    WAN_VIDEO_2_2_I2V_A_14_B……),`BaseModel` 是底模仓库(ModelE/Illustrious-XL、Qwen/Qwen-Image-2.1@master……)。
    两样都是架构名的写法,和文件头里的底模用同一张表:

    1. 类型认得就用它;是 SDXL 时,底模仓库名、再是它自己的仓库名和文件名(`own`)里带 illustrious / noob / pony 的,
       细分成那一支(和 `family_of` 第 3 条同一个规矩:Illustrious 本身登记成 SDXL 上的 Checkpoint);
    2. 类型没写(或 UNKNOWN)时看底模仓库名;
    3. 都认不出:底模仓库名原样交出(没有就类型原样),不往认得的家族上靠。
    """
    names = [one.strip().split("@")[0].split("/")[-1] for one in bases if one.strip() and one.strip() != "undefined"]
    kind = "" if vision.strip().upper() == "UNKNOWN" else vision.strip()
    label = _by_name(kind, _META_FAMILIES) or next((found for found in (_by_name(name, _META_FAMILIES) for name in names)
                                                   if found), "")
    if label == "SDXL":
        hints = (_by_name(name, _NAME_FAMILIES) for name in (*names, *own))
        return next((found for found in hints if found in _SDXL_BRANCHES), label)
    return label or (names[0] if names else kind)[:80]
