"""底模家族怎么认(ADR 0034 §2,规矩也写在插件 README 里):元数据 > 权重结构 > 文件名,认不出不猜。

模型库列表、Civitai / ModelScope 链接解析共用这一份;权重结构那张表在 weights.py。
"""

from __future__ import annotations

import re
from typing import Any

#: 放「给某个底模用的」东西的目录:元数据、权重结构都认不出时,在这些目录里才按文件名猜。
NAME_INFERRED_FOLDERS = frozenset({
    "checkpoints", "loras", "lycoris", "diffusion_models", "unet", "unet_gguf", "controlnet", "embeddings",
    "hypernetworks", "vae", "model_patches", "style_models", "ipadapter",
})
#: 「底模」这件事不适用的目录:文本编码器、CLIP 视觉、放大、检测 / 分割、抠图、语音和大语言模型……它们不是为某一个底模
#: 做的(一个叫 qwen3vl_4b 的文本编码器不是 Qwen-Image),界面上写「不适用」,不写「认不出」。按小写比。
#: `vosr2` 是 VOSR 2.0 超分的一整套(LightningDiT + 它专配的 Qwen-Image 2D VAE + DINOv2-L,一起训练、不能拆换):不是哪个
#: 底模的,里面那个 VAE 按权重认得出 Qwen-Image 的结构,却只能配它自己用。
NOT_APPLICABLE_FOLDERS = frozenset({
    "text_encoders", "clip", "clip_gguf", "t5", "clip_vision", "upscale_models", "sams", "sam2", "instantid",
    "insightface", "facerestore_models", "facedetection", "onnx", "rembg", "rmbg", "background_removal", "mediapipe",
    "detection", "frame_interpolation", "optical_flow", "geometry_estimation", "audio_encoders", "wav2vec2", "llm",
    "prompt_generator", "vosr2",
})
#: 同一类的一串目录(Impact Pack 的 ultralytics_bbox / ultralytics_segm,mmdets_bbox……)
NOT_APPLICABLE_PREFIXES = ("ultralytics", "mmdets")
#: `family_source` 的特殊值:这个目录不讲底模(和「认不出」分开,界面据此写「不适用」)。
NOT_APPLICABLE = "not_applicable"


def _rules(*pairs: tuple[str, str]) -> tuple[tuple[re.Pattern[str], str], ...]:
    return tuple((re.compile(pattern), label) for pattern, label in pairs)


#: 元数据里写的底模(`ss_base_model_version` / `modelspec.architecture`,ModelScope 登记的类型和底模仓库名)→ 家族。
#: 按先后认,认到为止。
_META_FAMILIES = _rules(
    (r"kontext", "Flux Kontext"),
    (r"flux[-_.]?2", "Flux.2"),
    (r"flux", "Flux"),
    (r"chroma", "Chroma"),
    (r"krea[-_ ]?2", "Krea 2"),
    # anima、anima-preview;animagine(SDXL 的一个模型)不算
    (r"(?:^|[^a-z])anima(?:[^a-z]|$)", "Anima"),
    (r"minimax[-_ ]?music", "MiniMax Music"),
    (r"minimax[-_ ]?h3", "MiniMax H3"),
    # qwen_image_2 / qwen_image_2.1;Qwen-Image-2512(还是第一代的结构)、ModelScope 的 QWEN_IMAGE_20_B(20B)不算
    (r"qwen[-_ ]?image[-_ ]?2(?:[._]\d)?(?!\d)", "Qwen-Image 2"),
    (r"qwen[-_ ]?image", "Qwen-Image"),
    (r"hidream", "HiDream"),
    # ModelScope 登记的底模类型写成 WAN_VIDEO_2_2_I2V_A_14_B
    (r"wan[-_. ]?(?:video[-_. ]?)?2[._]?2|wan22", "Wan 2.2"),
    (r"wan[-_. ]?(?:video[-_. ]?)?2[._]?1|wan21", "Wan 2.1"),
    # musubi-tuner 只写 wan:14B 的 2.1、2.2 结构一样,不替它挑一代
    (r"wan", "Wan"),
    # 混元的图像模型(HunyuanDiT、HunyuanImage)是另外几种结构,不算
    (r"hunyuan[-_ ]?video|hyvid", "HunyuanVideo"),
    (r"ltx", "LTX-Video"),
    (r"lumina", "Lumina"),
    (r"z[-_ ]?image", "Z-Image"),
    (r"sd3|stable-diffusion-3|sd_3", "SD 3"),
    # Pony V7 换成了 AuraFlow 的结构,不是 SDXL 上的那一支
    (r"pony[-_ ]?v7", "Pony V7"),
    (r"aura[-_ ]?flow", "AuraFlow"),
    (r"pony", "Pony"),
    (r"illustrious", "Illustrious"),
    (r"noob", "NoobAI"),
    (r"kolors", "Kolors"),
    (r"sdxl|stable-diffusion-xl|sd_xl", "SDXL"),
    # ModelScope 写成 SD_2 / SD_2_1
    (r"sd_?v?2|stable-diffusion-v2", "SD 2"),
    (r"sd_?v1|stable-diffusion-v1|sd_?1[._]?5|sd1", "SD 1.5"),
)
#: 文件名(连子目录,驼峰拆开)里的关键词 → 家族。SDXL 的几支(Illustrious、NoobAI、Pony)排在 SDXL 前面。
#: 短的缩写两头都要是非字母:`IL`、`XL`、`ZIT` 单独出现才算,animagine、animation、illustration 都不沾边。
_NAME_FAMILIES = _rules(
    # illustri:Illustrious 和照它起名的 illustrij 这类;illustration、illustrator 不沾边
    (r"illustri|(?:^|[^a-z])il(?:xl)?(?:[^a-z]|$)", "Illustrious"),
    (r"noob", "NoobAI"),
    (r"pony[-_ ]?v7", "Pony V7"),
    (r"aura[-_ ]?flow", "AuraFlow"),
    (r"pony|(?:^|[^a-z])pdxl", "Pony"),
    (r"kontext", "Flux Kontext"),
    (r"(?:^|[^a-z])flux[-_. ]?2", "Flux.2"),
    (r"(?:^|[^a-z])flux", "Flux"),
    (r"(?:^|[^a-z])chroma", "Chroma"),
    (r"krea[-_. ]?2", "Krea 2"),
    (r"(?:^|[^a-z])anima(?:[^a-z]|$)", "Anima"),
    (r"minimax[-_ ]?music", "MiniMax Music"),
    (r"minimax[-_ ]?h3", "MiniMax H3"),
    (r"qwen[-_ ]?image[-_ ]?2(?:[._]\d)?(?!\d)|qwen[-_ ]?2[._]?1(?!\d)", "Qwen-Image 2"),
    (r"qwen[-_ ]?image|(?:^|[^a-z])qwen(?:[^a-z]|$)", "Qwen-Image"),
    (r"hi[-_ ]?dream", "HiDream"),
    (r"wan[-_. ]?2[._]?2|wan22", "Wan 2.2"),
    (r"wan[-_. ]?2[._]?1|wan21", "Wan 2.1"),
    (r"(?:^|[^a-z])wan(?:[^a-z]|$)", "Wan"),
    (r"hunyuan[-_ ]?video|hyvid", "HunyuanVideo"),
    (r"ltx", "LTX-Video"),
    (r"lumina", "Lumina"),
    # ZIT 是 Z-Image Turbo 的常见缩写
    (r"z[-_ ]?image|(?:^|[^a-z])zit(?:[^a-z]|$)", "Z-Image"),
    (r"(?:^|[^a-z])sd[-_ ]?3", "SD 3"),
    (r"kolors", "Kolors"),
    (r"sdxl|sd_xl|(?:^|[^a-z])xl(?:[^a-z]|$)", "SDXL"),
    (r"sd[-_ ]?1[._]?5|v1[-_]5|sd15", "SD 1.5"),
)
#: 认出的那一层还能再细分的:权重结构看不出 Illustrious 和 SDXL 的差别、Wan 14B 的 2.1 和 2.2、Kontext 和 Flux dev。
BRANCHES: dict[str, tuple[str, ...]] = {
    # Kolors 的 LoRA、IP-Adapter 和 SDXL 的层一模一样(大模型才多一层 encoder_hid_proj)
    "SDXL": ("Illustrious", "NoobAI", "Pony", "Kolors"),
    "Wan": ("Wan 2.2", "Wan 2.1"),
    "Flux": ("Flux Kontext", "Chroma"),
    "AuraFlow": ("Pony V7",),
}
#: 细分用的关键词(只在已经认出是那一层之后用,所以可以比 _NAME_FAMILIES 宽:`ILL`、`illu` 单独当文件名猜太冒险,
#: 已经知道是 SDXL 时就是 Illustrious;Wan 2.2 的 14B 分高噪、低噪两个专家,文件名里带 high noise / low noise 的是 2.2)。
_BRANCH_HINTS = _rules(
    (r"illustri|(?:^|[^a-z])(?:il|ill|illu|ilxl|illxl)(?:[^a-z]|$)", "Illustrious"),
    (r"noob", "NoobAI"),
    (r"pony[-_ ]?v7", "Pony V7"),
    (r"pony|(?:^|[^a-z])pdxl", "Pony"),
    (r"kolors", "Kolors"),
    (r"wan[-_. ]?2[._]?2|wan22|(?:high|low)[-_ ]?noise", "Wan 2.2"),
    (r"wan[-_. ]?2[._]?1|wan21", "Wan 2.1"),
    (r"kontext", "Flux Kontext"),
    (r"(?:^|[^a-z])chroma", "Chroma"),
)
#: Civitai 在线训练写进 `ss_sd_model_name` 的是底模的版本号(`889818.safetensors`)或 AIR(`urn:air:sdxl:checkpoint:
#: civitai:1369089@1546777`):SDXL 那几支官方底模的版本号 → 那一支(在 Civitai 上逐个查过)。别的版本号是大家自己的
#: 模型,不认。
CIVITAI_TRAINER_BASES = {
    "290640": "Pony",  # Pony Diffusion V6 XL
    "889818": "Illustrious",  # Illustrious-XL v0.1
    "1546777": "Illustrious",  # Illustrious XL 2.0
    "1190596": "NoobAI",  # NoobAI-XL V-Pred 1.0
}
_CIVITAI_VERSION = re.compile(r"^(?:urn:air:\w+:\w+:civitai:\d+@)?(\d+)(?:\.safetensors)?$")
#: 驼峰拆词:novaAnimeXL_ilV160 → nova Anime XL_il V160,XL、il 才算单独出现
_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def _by_name(text: str, rules: tuple[tuple[re.Pattern[str], str], ...]) -> str:
    """原样小写和驼峰拆开的各认一遍(`MiniMax`、`HiDream` 拆开就认不出,`flatbreadIL` 不拆认不出),按表的先后。"""
    words = f"{text.lower()} {_CAMEL.sub(' ', text).lower()}"
    return next((label for pattern, label in rules if pattern.search(words)), "")


def family_applies(folder: str) -> bool:
    """这个目录讲不讲底模(见 NOT_APPLICABLE_FOLDERS)。"""
    lowered = folder.lower()
    return lowered not in NOT_APPLICABLE_FOLDERS and not lowered.startswith(NOT_APPLICABLE_PREFIXES)


def _declared(meta: dict[str, Any]) -> tuple[str, str]:
    """元数据说的底模:(认出的家族, 原文)。

    `ss_base_model_version`(kohya 写的,最具体)先看:训练脚本不认识的底模它照写(anima、krea2),`modelspec.architecture`
    却照默认写成 stable-diffusion-v1,不能信后者。都没有、又是 kohya 训出来的(有 `ss_network_*`)时,老版本(SDXL 之前)
    只写了 `ss_v2`:True 是 SD 2,False 是 SD 1。"""
    for key in ("ss_base_model_version", "modelspec.architecture"):
        raw = meta.get(key)
        if isinstance(raw, str) and raw.strip():
            value = raw.strip().split("/")[0]
            return _by_name(value, _META_FAMILIES), value
    if any(str(key).startswith("ss_network_") for key in meta):
        v2 = str(meta.get("ss_v2") or "").strip().lower()
        if v2 in ("true", "false"):
            return ("SD 2" if v2 == "true" else "SD 1.5"), ""
    return "", ""


def _narrowed(family: str, source: str, meta: dict[str, Any], stem: str) -> tuple[str, str]:
    """认出的是分不细的那一层(SDXL、Wan、Flux)时,训练用的底模名 / 标题、再是文件名细分到那一支。"""
    branches = BRANCHES.get(family)
    if not branches:
        return family, source
    trained_on = str(meta.get("ss_sd_model_name") or "").strip()
    version = _CIVITAI_VERSION.match(trained_on)
    if version:
        trained_on = CIVITAI_TRAINER_BASES.get(version.group(1), "")
    hint = _by_name(f"{trained_on} {meta.get('modelspec.title') or ''}", _BRANCH_HINTS)
    if hint in branches:
        return hint, "metadata"
    from_name = _by_name(stem, _BRANCH_HINTS)
    if from_name in branches:
        return from_name, "filename"
    return family, source


def refined_by_civitai(family: str, source: str, base_model: str) -> tuple[str, str]:
    """Civitai 上登记的底模(按哈希对上的版本、经 Mosael 从 Civitai 下的)细分一下:元数据、权重只看得出 SDXL / Wan / Flux
    这一层时,换成 Civitai 说的那一支(Illustrious、Wan 2.2……),凭的写 `civitai`。认不出底模、只凭文件名猜的,用
    Civitai 的(它说的是这个文件本身);元数据、权重已经认出一支的,不改。"""
    found = family_from_base(base_model)
    if not found or source == NOT_APPLICABLE:
        return family, source
    if family in BRANCHES and found in BRANCHES[family] and found != family:
        return found, "civitai"
    if not family or source == "filename":
        return found, "civitai"
    return family, source


def family_of(folder: str, name: str, meta: dict[str, Any], weights: str = "") -> tuple[str, str]:
    """推断的底模家族和凭的是什么(`metadata` / `weights` / `filename`);认不出是 ("", ""),这个目录不讲底模是
    ("", "not_applicable")。`weights` 是 weights.py 从文件头的张量认出的家族(没读到就是空串)。规矩写在插件 README 里:

    1. 元数据(`_declared`);
    2. 权重结构:和元数据对得上(一样,或元数据更细:权重只看得出 SDXL,元数据说 Pony)用元数据;对不上架构时信权重 ——
       元数据写错的不少(Flux 的 LoRA 写着 sd_1.5);元数据是表里没有的值时也用权重;
    3. 认出的是 SDXL / Wan / Flux 这一层时,训练用的底模名、标题,再是文件名细分到那一支;
    4. 都没有时看文件名(连子目录)—— 只在放「给某个底模用的东西」的目录里猜;
    5. 元数据里写了、表里没有、权重也认不出的值原样交出,不往认得的家族上靠。
    """
    if not family_applies(folder):
        return "", NOT_APPLICABLE
    stem = name.replace("\\", "/")
    declared, raw = _declared(meta)
    if declared and (not weights or declared == weights or declared in BRANCHES.get(weights, ())):
        return _narrowed(declared, "metadata", meta, stem)
    if weights:
        return _narrowed(weights, "weights", meta, stem)
    if raw:
        return raw[:80], "metadata"
    if folder in NAME_INFERRED_FOLDERS:
        label = _by_name(stem, _NAME_FAMILIES)
        if label:
            return label, "filename"
    return "", ""


#: Civitai 的 `baseModel`(「SDXL 1.0」「Illustrious」「Flux.1 D」「Wan Video 2.2 T2V-A14B」……)→ 家族。
_BASE_FAMILIES = _rules(
    (r"kontext", "Flux Kontext"),
    (r"flux\.?2", "Flux.2"),
    # Flux.1 Krea 也在这里:它是 Flux
    (r"flux", "Flux"),
    (r"krea ?2", "Krea 2"),
    (r"(?:^|[^a-z])anima(?:[^a-z]|$)", "Anima"),
    (r"minimax ?music", "MiniMax Music"),
    (r"minimax ?h3", "MiniMax H3"),
    (r"pony ?v7", "Pony V7"),
    (r"aura ?flow", "AuraFlow"),
    (r"illustrious", "Illustrious"),
    (r"noob", "NoobAI"),
    (r"pony", "Pony"),
    (r"kolors", "Kolors"),
    (r"sdxl", "SDXL"),
    (r"sd ?3", "SD 3"),
    (r"sd ?2", "SD 2"),
    (r"sd ?1", "SD 1.5"),
    (r"wan(?: video)? ?2\.2", "Wan 2.2"),
    # Civitai 把 2.1 记成「Wan Video 14B t2v」「Wan Video 1.3B t2v」「Wan Video 14B i2v 480p」
    (r"wan(?: video)? ?2\.1|wan video (?:14b|1\.3b)", "Wan 2.1"),
    (r"wan", "Wan"),
    (r"hunyuan ?video", "HunyuanVideo"),
    (r"ltx", "LTX-Video"),
    # Qwen 2 / Qwen 2.1 是 Qwen-Image 2;光写 Qwen 的是第一代
    (r"qwen ?2(?:\.\d)?(?!\d)", "Qwen-Image 2"),
    (r"qwen", "Qwen-Image"),
    (r"hidream", "HiDream"),
    (r"chroma", "Chroma"),
    (r"lumina", "Lumina"),
    (r"z ?image", "Z-Image"),
)


def family_from_base(base: str) -> str:
    """Civitai 写的底模 → 家族;表里没有的原样交出(不往认得的家族上靠),「Other」等于没说。"""
    text = (base or "").strip()
    if not text or text.lower() == "other":
        return ""
    return _by_name(text, _BASE_FAMILIES) or text[:80]


def family_from_modelscope(vision: str, bases: list[str], own: tuple[str, ...] = ()) -> str:
    """ModelScope AIGC 专区登记的底模 → 家族。`VisionFoundation` 是它的底模类型(SD_XL、FLUX_1、QWEN_IMAGE_20_B、
    WAN_VIDEO_2_2_I2V_A_14_B……),`BaseModel` 是底模仓库(ModelE/Illustrious-XL、Qwen/Qwen-Image-2.1@master……)。
    两样都是架构名的写法,和文件头里的底模用同一张表:

    1. 类型认得就用它;是 SDXL 这种分不细的一层时,底模仓库名、再是它自己的仓库名和文件名(`own`)细分到那一支
       (和 `family_of` 第 3 条同一个规矩:Illustrious 本身登记成 SDXL 上的 Checkpoint);
    2. 类型没写(或 UNKNOWN)时看底模仓库名;
    3. 都认不出:底模仓库名原样交出(没有就类型原样),不往认得的家族上靠。
    """
    names = [one.strip().split("@")[0].split("/")[-1] for one in bases if one.strip() and one.strip() != "undefined"]
    kind = "" if vision.strip().upper() == "UNKNOWN" else vision.strip()
    label = _by_name(kind, _META_FAMILIES) or next((found for found in (_by_name(name, _META_FAMILIES) for name in names)
                                                   if found), "")
    if label in BRANCHES:
        hints = (_by_name(name, _BRANCH_HINTS) for name in (*names, *own))
        return next((found for found in hints if found in BRANCHES[label]), label)
    return label or (names[0] if names else kind)[:80]
