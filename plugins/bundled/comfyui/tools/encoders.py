"""文本编码器是哪一种、常配哪几种底模(ADR 0034 §2 的 2026-10-07 补记;规矩也写在插件 README 里)。

一个文本编码器不是给某一个底模做的 —— T5-XXL 给 Flux、SD 3、HiDream 都用,一个叫 qwen3vl_4b 的配的是 Krea 2,不是
Qwen-Image。所以它照旧不贴底模(`family` 空着、`family_source` 是 not_applicable,families.py 管),这里另说两件事:

- **是哪一种**:和 ComfyUI 一样看权重 —— CLIPLoader 读进文件之后,先认它装的是哪一种编码器,再按节点上选的 type 建对应的
  那一路。认的是文件头里就有的张量名和形状,不下整个文件:CLIP 的文本塔数层数(L 12、H 24、G 32);T5 一系看宽度、前馈宽度、
  前馈有没有门控、是不是每一块都带相对位置偏置(UMT5 / Pile-T5 每块都有,T5 / mT5 / ByT5 只有第一块有);解码器式的语言模型先看
  是哪一系(Gemma 有前馈之后的归一化、Qwen2.5 的 k 投影带偏置、Qwen3 有 q_norm、Qwen3-VL 的视觉塔有 deepstack、Qwen3.5 是线性
  注意力),再看宽度和层数。只看不会被量化改形状的那几样(归一化的向量、输出那一维),fp8 / int8 / nvfp4 的文件一样认。
  GGUF 看 `general.architecture` 和它写在键值里的宽度、词表大小(model_files 只读开头一段:词表本身跟在后面,几 MB,不读)。
- **常配哪几种底模**:照 ComfyUI 自己的加载规矩抄的(见 RECIPES)。家族名和 families.py 的一致,模型库按底模筛时据此把常配的
  编码器一起列出来(标「常配」,不算那个底模的)。

先后和 families.py 一样是「元数据 > 权重 > 文件名」,只是这些文件不在元数据里写自己是哪一种(维护者那台的 11 个只有 Comfy-Org
新打包的两个写了 `comfy_model`,权重本来就认得),所以就是「权重 > 文件名」:权重认得就用权重(`weights`);读不到文件头(没装
ComfyUI-Custom-Scripts、`.bin` / `.pt`)或读到了认不出时才按文件名猜(`filename`,界面上标明是猜的);都不行就是认不出,不往
认得的种类上靠。

这些表写的是事实(公开的模型结构:哪种编码器有哪些层、多宽;ComfyUI 的加载规矩:哪个 type 用哪种编码器),对着实际文件核过,
不照搬 ComfyUI 的代码(GPL)。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from families import BRANCHES

#: 放文本编码器的目录(ComfyUI 的 folder_paths 名,按小写比):`clip` 是 `text_encoders` 的老名字,`clip_gguf` 是 ComfyUI-GGUF
#: 登记的、和它指着同一批文件夹,`t5` 是更老的。families.NOT_APPLICABLE_FOLDERS 里也有它们 —— 底模这件事照旧不适用。
ENCODER_FOLDERS = frozenset({"text_encoders", "clip", "clip_gguf", "t5"})


@dataclass(frozen=True)
class Kind:
    """一种文本编码器:`id` 是给宿主和界面认的(界面按它判合不合工作台里那个节点的 type),`label` 是给人看的名字(都是专名,
    中英文一样)。"""

    id: str
    label: str


KINDS: tuple[Kind, ...] = (
    Kind("clip_l", "CLIP-L"), Kind("clip_h", "CLIP-H"), Kind("clip_g", "CLIP-G"),
    Kind("t5_xxl", "T5-XXL"), Kind("umt5_xxl", "UMT5-XXL"), Kind("t5_xxl_v1", "T5-XXL v1.0"), Kind("t5_xl", "Pile-T5-XL"),
    Kind("mt5_xl", "mT5-XL"), Kind("t5_base", "T5-Base"), Kind("umt5_base", "UMT5-Base"), Kind("byt5_small", "ByT5-Small"),
    Kind("t5_gemma", "T5Gemma"),
    Kind("llama3_8b", "Llama 3 8B"), Kind("mistral3_24b", "Mistral Small 3 24B"), Kind("ministral3_3b", "Ministral 3 3B"),
    Kind("gemma2_2b", "Gemma 2 2B"), Kind("gemma3_4b", "Gemma 3 4B"), Kind("gemma3_12b", "Gemma 3 12B"),
    Kind("gemma4_e2b", "Gemma 4 E2B"), Kind("gemma4_e4b", "Gemma 4 E4B"), Kind("gemma4_12b", "Gemma 4 12B"),
    Kind("gemma4_31b", "Gemma 4 31B"),
    Kind("qwen25_3b", "Qwen2.5-VL 3B"), Kind("qwen25_7b", "Qwen2.5-VL 7B"),
    Kind("qwen3_06b", "Qwen3 0.6B"), Kind("qwen3_2b", "Qwen3 2B"), Kind("qwen3_4b", "Qwen3 4B"), Kind("qwen3_8b", "Qwen3 8B"),
    Kind("qwen3vl_4b", "Qwen3-VL 4B"), Kind("qwen3vl_8b", "Qwen3-VL 8B"), Kind("qwen3vl_32b", "Qwen3-VL 32B"),
    Kind("qwen35", "Qwen3.5"), Kind("qwen35_08b", "Qwen3.5 0.8B"), Kind("qwen35_2b", "Qwen3.5 2B"),
    Kind("qwen35_4b", "Qwen3.5 4B"), Kind("qwen35_9b", "Qwen3.5 9B"), Kind("qwen35_27b", "Qwen3.5 27B"),
    Kind("jina_clip_v2", "Jina CLIP v2"), Kind("gpt_oss_20b", "GPT-OSS 20B"), Kind("ming_image", "Ming"),
    Kind("minimax_music3", "MiniMax Music 3"), Kind("yue2", "YuE 2"),
)
LABELS = {one.id: one.label for one in KINDS}


# --- 从权重认:张量名和形状 ----------------------------------------------------------------------

#: 只有这一种才有的张量(名字原样比)。几样都写了的要都在。
UNIQUE: tuple[tuple[str, tuple[str, ...]], ...] = (
    # MiniMax Music 3 的编码器带一个出音频的解码头;它的语言模型部分和 Qwen3 8B 一样宽,得先认它
    ("minimax_music3", ("model.audio_decoder.projection.weight",)),
    ("yue2", ("yue2_tokenizer_json",)),
    ("ming_image", ("thinker.layers.1.mlp.image_gate.proj.weight",)),
    ("jina_clip_v2", ("model.encoder.layers.0.mixer.Wqkv.weight",)),
    ("t5_gemma", ("model.encoder.layers.0.pre_self_attn_layernorm.weight",)),
    ("gpt_oss_20b", ("layers.0.self_attn.sinks", "layers.0.mlp.experts.gate_up_proj.weight")),
)
#: CLIP 的文本塔(transformers 写法 `text_model.encoder.layers.N.`,OpenCLIP 写法 `transformer.resblocks.N.`):层数 → 种类
CLIP_LAYERS = {12: "clip_l", 24: "clip_h", 32: "clip_g"}
#: T5 一系的编码器:(前馈有门控, 宽, 前馈宽, 每一块都带相对位置偏置) → 种类
T5 = {
    (True, 4096, 10240, False): "t5_xxl",  # T5 v1.1 XXL
    (True, 4096, 10240, True): "umt5_xxl",  # 和 T5-XXL 一样宽,词表大八倍、每块都有偏置 —— ComfyUI 自己不分,靠 type 选 wan
    (False, 1024, 65536, False): "t5_xxl_v1",  # 最早的 T5 11B(Cosmos 用的「old t5」)
    (True, 2048, 5120, True): "t5_xl",  # Pile-T5-XL(AuraFlow)
    (True, 2048, 5120, False): "mt5_xl",  # mT5-XL(HunyuanDiT):同样宽,只有第一块有偏置
    (False, 768, 3072, False): "t5_base",
    (True, 768, 2048, True): "umt5_base",
    (True, 1472, 3584, False): "byt5_small",  # Glyph-ByT5 Small(HunyuanVideo 1.5、HunyuanImage 写字用)
}
#: 解码器式的语言模型:(哪一系, 宽, 层数) → 种类;层数是 0 的不看层数
LANGUAGE_MODELS = {
    ("gemma2", 2304, 0): "gemma2_2b",
    ("gemma", 2560, 34): "gemma3_4b", ("gemma", 3840, 48): "gemma3_12b",
    ("gemma", 1536, 35): "gemma4_e2b", ("gemma", 2560, 42): "gemma4_e4b", ("gemma", 5376, 60): "gemma4_31b",
    ("qwen2", 2048, 0): "qwen25_3b", ("qwen2", 3584, 0): "qwen25_7b",
    ("qwen3", 1024, 0): "qwen3_06b", ("qwen3", 2048, 0): "qwen3_2b", ("qwen3", 2560, 0): "qwen3_4b",
    ("qwen3", 4096, 0): "qwen3_8b",
    ("qwen3vl", 2560, 0): "qwen3vl_4b", ("qwen3vl", 4096, 0): "qwen3vl_8b", ("qwen3vl", 5120, 0): "qwen3vl_32b",
    ("qwen35", 1024, 0): "qwen35_08b", ("qwen35", 2048, 0): "qwen35_2b", ("qwen35", 2560, 0): "qwen35_4b",
    ("qwen35", 4096, 0): "qwen35_9b", ("qwen35", 5120, 0): "qwen35_27b",
    ("llama", 4096, 0): "llama3_8b", ("llama", 5120, 0): "mistral3_24b", ("llama", 3072, 0): "ministral3_3b",
}
#: 那一系认得、宽度不认得时说到哪一层(不往某个尺寸上靠)
SERIES_ONLY = {"qwen35": "qwen35"}
#: GGUF(ComfyUI-GGUF 认的文本编码器架构):T5 看(宽, 词表大小),别的看宽度 —— 都写在文件头的键值里
GGUF_T5 = {(4096, 32128): "t5_xxl", (4096, 256384): "umt5_xxl", (2048, 32128): "t5_xl", (2048, 250112): "mt5_xl",
           (768, 32128): "t5_base", (768, 256384): "umt5_base"}
GGUF_SERIES = {"llama": "llama", "qwen2vl": "qwen2", "qwen3": "qwen3", "qwen3vl": "qwen3vl", "gemma3": "gemma3"}
GGUF_GEMMA3 = {2560: "gemma3_4b", 3840: "gemma3_12b"}

#: 这几张表的指纹:缓存里记着「这个文件认成了哪一种」,表一改就得重认(见 library 的缓存版本)。
DIGEST = hashlib.sha1(repr((UNIQUE, sorted(CLIP_LAYERS.items()), sorted(T5.items()), sorted(LANGUAGE_MODELS.items()),
                            sorted(SERIES_ONLY.items()), sorted(GGUF_T5.items()), sorted(GGUF_SERIES.items()),
                            sorted(GGUF_GEMMA3.items()))).encode("utf-8")).hexdigest()[:12]


def _first(shape: Sequence[Any] | None) -> int:
    return shape[0] if shape and isinstance(shape[0], int) else 0


def _layer_count(tensors: Mapping[str, Any], prefix: str) -> int:
    """`prefix` 后面跟着块号的那些张量:最大的块号 + 1(没有是 0)。"""
    found = 0
    for key in tensors:
        if key.startswith(prefix):
            head = key[len(prefix):].split(".", 1)[0]
            if head.isdigit():
                found = max(found, int(head) + 1)
    return found


def _t5(tensors: Mapping[str, Sequence[Any]]) -> str:
    gated = "encoder.block.0.layer.1.DenseReluDense.wi_0.weight" in tensors
    feed = _first(tensors.get("encoder.block.0.layer.1.DenseReluDense." + ("wi_1" if gated else "wi") + ".weight"))
    width = _first(tensors.get("encoder.final_layer_norm.weight"))
    every_block = "encoder.block.1.layer.0.SelfAttention.relative_attention_bias.weight" in tensors
    return T5.get((gated, width, feed, every_block), "")


def _language_model(tensors: Mapping[str, Sequence[Any]]) -> str:
    """解码器式的语言模型(`model.layers.N.`,Qwen3-VL / Qwen3.5 的是 `model.language_model.layers.N.`)。"""
    for prefix in ("model.layers.", "model.language_model.layers."):
        width = _first(tensors.get(prefix + "0.input_layernorm.weight"))
        if width:
            break
    else:
        return ""
    first = prefix + "0."
    if first + "linear_attn.A_log" in tensors:
        series, layers = "qwen35", 0
    elif first + "post_feedforward_layernorm.weight" in tensors:
        series = "gemma" if first + "self_attn.q_norm.weight" in tensors else "gemma2"
        layers = _layer_count(tensors, prefix) if series == "gemma" else 0
    elif first + "self_attn.k_proj.bias" in tensors:
        series, layers = "qwen2", 0
    elif first + "self_attn.q_norm.weight" in tensors:
        series, layers = "qwen3", 0
    else:
        series, layers = "llama", 0
    found = LANGUAGE_MODELS.get((series, width, layers), "") or SERIES_ONLY.get(series, "")
    # Gemma 3 12B 和 Gemma 4 12B 一样宽、一样多层:Gemma 4 的全局注意力层(每六层一层,第一个是第 5 层)没有 v 投影
    if found == "gemma3_12b" and prefix + "5.self_attn.v_proj.weight" not in tensors:
        return "gemma4_12b"
    return found


def kind_of_weights(tensors: Mapping[str, Sequence[Any]]) -> str:
    """张量名 → 形状(safetensors 的文件头)→ 哪一种文本编码器;认不出是空串。"""
    if not tensors:
        return ""
    for kind, keys in UNIQUE:
        if all(key in tensors for key in keys):
            return kind
    layers = _layer_count(tensors, "text_model.encoder.layers.") or _layer_count(tensors, "transformer.resblocks.")
    if layers:
        return CLIP_LAYERS.get(layers, "")
    if "encoder.block.0.layer.0.SelfAttention.k.weight" in tensors:
        return _t5(tensors)
    for prefix in ("model.visual.", "visual."):
        if prefix + "deepstack_merger_list.0.norm.weight" in tensors:
            width = _first(tensors.get(prefix + "merger.linear_fc2.weight"))
            return LANGUAGE_MODELS.get(("qwen3vl", width, 0), "")
    return _language_model(tensors)


def kind_of_gguf(architecture: str, sizes: Mapping[str, int]) -> str:
    """GGUF 的 `general.architecture` 和键值里的宽度(`embedding_length`)、词表大小(`vocab`)→ 哪一种;认不出是空串。"""
    arch = (architecture or "").strip().lower()
    width = int(sizes.get("embedding_length") or 0)
    if arch in ("t5", "t5encoder"):
        return GGUF_T5.get((width, int(sizes.get("vocab") or 0)), "")
    if arch == "gemma3":
        return GGUF_GEMMA3.get(width, "")
    series = GGUF_SERIES.get(arch)
    return LANGUAGE_MODELS.get((series, width, 0), "") if series else ""


def kind_of_header(tensors: Mapping[str, Sequence[Any]], architecture: str = "", sizes: Mapping[str, int] | None = None) -> str:
    """读到的文件头 → 哪一种:safetensors 看张量表,GGUF 看架构名和键值(它的张量表在词表后面,不读)。"""
    return kind_of_weights(tensors) or (kind_of_gguf(architecture, sizes or {}) if architecture else "")


# --- 读不到文件头时:按文件名猜 --------------------------------------------------------------------

def _rules(*pairs: tuple[str, str]) -> tuple[tuple[re.Pattern[str], str], ...]:
    return tuple((re.compile(pattern), kind) for pattern, kind in pairs)


#: 文件名(连子目录,小写)里的写法 → 种类。按先后认:包含别的写法的排前面(umt5_xxl 里有 t5_xxl,mt5_xl 里有 t5_xl,
#: qwen3.5 / qwen3vl 在 qwen3 前面)。写法照 ComfyUI 官方模板和 Comfy-Org 打包的文件名。
NAME_RULES = _rules(
    (r"umt5[-_ ]?xxl", "umt5_xxl"),
    (r"umt5[-_ ]?base", "umt5_base"),
    (r"old[-_ ]?t5", "t5_xxl_v1"),
    (r"t5[-_ ]?gemma", "t5_gemma"),
    (r"mt5[-_ ]?xl", "mt5_xl"),
    (r"pile[-_ ]?t5|(?:^|[^a-z])t5[-_ ]?xl(?!l)", "t5_xl"),
    (r"byt5", "byt5_small"),
    (r"t5[-_ ]?v1[-_.]1[-_ ]?xxl|t5[-_ ]?xxl", "t5_xxl"),
    (r"t5[-_ ]?base", "t5_base"),
    (r"(?:^|[^a-z])clip[-_ ]?l(?![a-z])|vit[-_ ]?l[-_ ]?14", "clip_l"),
    (r"(?:^|[^a-z])clip[-_ ]?g(?![a-z])|vit[-_ ]?bigg", "clip_g"),
    (r"(?:^|[^a-z])clip[-_ ]?h(?![a-z])|vit[-_ ]?h[-_ ]?14", "clip_h"),
    (r"jina[-_ ]?clip", "jina_clip_v2"),
    (r"llava[-_ ]?llama[-_ ]?3|llama[-_ ]?3(?:[._]\d)?[-_ ]?8b", "llama3_8b"),
    (r"mistral[-_ ]?3[-_ ]?small|mistral[-_ ]?small[-_ ]?3", "mistral3_24b"),
    (r"ministral[-_ ]?3[-_ ]?3b", "ministral3_3b"),
    (r"gemma[-_ ]?2[-_ ]?2b", "gemma2_2b"),
    (r"gemma[-_ ]?3[-_ ]?4b", "gemma3_4b"),
    (r"gemma[-_ ]?3[-_ ]?12b", "gemma3_12b"),
    (r"gemma[-_ ]?4[-_ ]?e2b", "gemma4_e2b"),
    (r"gemma[-_ ]?4[-_ ]?e4b", "gemma4_e4b"),
    (r"gemma[-_ ]?4[-_ ]?12b", "gemma4_12b"),
    (r"gemma[-_ ]?4[-_ ]?31b", "gemma4_31b"),
    (r"qwen[-_ ]?2[._]?5[-_ ]?vl[-_ ]?7b", "qwen25_7b"),
    (r"qwen[-_ ]?2[._]?5[-_ ]?vl[-_ ]?3b", "qwen25_3b"),
    (r"qwen[-_ ]?3[._]5[-_ ]?0[._]8b", "qwen35_08b"),
    (r"qwen[-_ ]?3[._]5[-_ ]?2b", "qwen35_2b"),
    (r"qwen[-_ ]?3[._]5[-_ ]?4b", "qwen35_4b"),
    (r"qwen[-_ ]?3[._]5[-_ ]?9b", "qwen35_9b"),
    (r"qwen[-_ ]?3[._]5[-_ ]?27b", "qwen35_27b"),
    (r"qwen[-_ ]?3[-_ ]?vl[-_ ]?4b", "qwen3vl_4b"),
    (r"qwen[-_ ]?3[-_ ]?vl[-_ ]?8b", "qwen3vl_8b"),
    (r"qwen[-_ ]?3[-_ ]?vl[-_ ]?32b", "qwen3vl_32b"),
    (r"qwen[-_ ]?(?:3[-_ ]?)?0[._]?6b", "qwen3_06b"),
    (r"qwen[-_ ]?3[-_ ]?(?:1[._]7|2)b", "qwen3_2b"),
    (r"qwen[-_ ]?(?:3[-_ ]?)?4b", "qwen3_4b"),
    (r"qwen[-_ ]?3[-_ ]?8b", "qwen3_8b"),
    (r"gpt[-_ ]?oss[-_ ]?20b", "gpt_oss_20b"),
    (r"minimax[-_ ]?music", "minimax_music3"),
)


def kind_of_name(name: str) -> str:
    """文件名(连子目录)→ 猜是哪一种;没有线索是空串。只在读不到、认不出文件头时用。"""
    lowered = name.replace("\\", "/").lower()
    return next((kind for pattern, kind in NAME_RULES if pattern.search(lowered)), "")


# --- 常配哪几种底模:ComfyUI 的加载规矩 ------------------------------------------------------------

#: 建这一路时 ComfyUI 不看 type(这几种编码器不论 type 选什么都建成同一路)。
ANY_TYPE = "*"


@dataclass(frozen=True)
class Recipe:
    """ComfyUI 的 CLIP 加载节点读 `files` 个文件、type 是 `type` 时,`kinds` 里的编码器建成的是给 `families` 用的那一路
    (`families` 空着:给的是 Mosael 不认作家族的底模,只用来判工作台里合不合那个 type)。"""

    files: int
    type: str
    kinds: tuple[str, ...]
    families: tuple[str, ...] = ()


#: 抄自 ComfyUI 0.39.0:`comfy/sd.py` 的 `load_text_encoder_state_dicts`(一个文件时按认出的编码器和 type 分支、两个文件时
#: 按 type 分支,三个是 SD 3、四个是 HiDream)、`detect_te_model`;`nodes.py` 的 CLIPLoader、DualCLIPLoader 和
#: `comfy_extras/nodes_sd3.py` 的 TripleCLIPLoader、`nodes_hidream.py` 的 QuadrupleCLIPLoader 列的 type 和配方说明;
#: 对着它带的官方模板(blueprints 里 CLIPLoader 选的文件和 type)核过。ComfyUI-GGUF 的四个 GGUF 加载节点用同一套 type。
#: 家族名必须是 families.py 里的(测试钉着)。先后就是界面上「常配」的先后:常见的在前,细分的那一支排到最后(见 pairs)。
RECIPES: tuple[Recipe, ...] = (
    Recipe(2, "sdxl", ("clip_l", "clip_g"), ("SDXL", "Illustrious", "NoobAI", "Pony")),  # Kolors 的文本是 ChatGLM,不在这里
    Recipe(1, "stable_diffusion", ("clip_l",), ("SD 1.5",)),
    Recipe(1, "stable_diffusion", ("clip_h",), ("SD 2",)),
    Recipe(1, "stable_diffusion", ("clip_g",), ("SDXL",)),  # 只有 CLIP-G 的是 SDXL 精炼模型那一路
    Recipe(2, "flux", ("clip_l", "t5_xxl"), ("Flux", "Flux Kontext")),
    Recipe(1, "sd3", ("clip_l", "clip_g", "t5_xxl"), ("SD 3",)),
    Recipe(2, "sd3", ("clip_l", "clip_g", "t5_xxl"), ("SD 3",)),
    Recipe(3, "sd3", ("clip_l", "clip_g", "t5_xxl"), ("SD 3",)),
    Recipe(1, "hidream", ("llama3_8b", "t5_xxl", "clip_l", "clip_g"), ("HiDream",)),
    Recipe(2, "hidream", ("llama3_8b", "t5_xxl", "clip_l", "clip_g"), ("HiDream",)),
    Recipe(4, "hidream", ("llama3_8b", "t5_xxl", "clip_l", "clip_g"), ("HiDream",)),
    Recipe(1, "wan", ("umt5_xxl",), ("Wan", "Wan 2.2", "Wan 2.1")),
    Recipe(1, "qwen_image", ("qwen25_7b",), ("Qwen-Image",)),
    Recipe(1, "qwen_image", ("qwen3vl_8b",), ("Qwen-Image 2",)),  # Qwen-Image 2.1 换成了整个 Qwen3-VL 8B
    Recipe(1, "krea2", ("qwen3vl_4b",), ("Krea 2",)),
    Recipe(1, "lumina2", ("qwen3_4b",), ("Z-Image",)),  # Z-Image 的模板选 lumina2
    Recipe(1, "lumina2", ("gemma2_2b",), ("Lumina",)),
    Recipe(2, "newbie", ("gemma3_4b", "jina_clip_v2"), ("Lumina",)),  # NewBie 照 Lumina 2 做的,Civitai 也记成 Lumina
    Recipe(1, "flux2", ("mistral3_24b", "qwen3_4b", "qwen3_8b", "qwen3vl_4b", "qwen3vl_8b"), ("Flux.2",)),  # dev、klein 4B / 9B
    Recipe(1, "chroma", ("t5_xxl",), ("Chroma",)),
    Recipe(1, "ltxv", ("t5_xxl", "gemma3_12b", "gemma4_12b"), ("LTX-Video",)),
    Recipe(2, "ltxv", ("gemma3_12b", "gemma4_e2b", "gemma4_e4b", "gemma4_12b", "gemma4_31b"), ("LTX-Video",)),
    Recipe(2, "hunyuan_video", ("clip_l", "llama3_8b"), ("HunyuanVideo",)),
    Recipe(2, "hunyuan_video_15", ("qwen25_7b", "byt5_small"), ("HunyuanVideo",)),
    Recipe(1, "minimax", ("qwen3vl_32b",), ("MiniMax H3",)),
    Recipe(1, "minimax", ("minimax_music3",), ("MiniMax Music",)),
    # 给的是 Mosael 不认作家族的底模
    Recipe(1, "stable_cascade", ("clip_g",)),
    Recipe(1, "stable_audio", ("t5_base",)),
    Recipe(1, "mochi", ("t5_xxl",)),
    Recipe(1, "pixart", ("t5_xxl",)),
    Recipe(1, "cogvideox", ("t5_xxl",)),
    Recipe(1, "cosmos", ("t5_xxl_v1",)),
    Recipe(1, "ace", ("umt5_base",)),
    Recipe(2, "ace", ("qwen3_06b", "qwen3_2b", "qwen3_4b")),
    Recipe(1, "omnigen2", ("qwen25_3b",)),
    Recipe(1, "hunyuan_image", ("qwen25_7b",)),
    Recipe(2, "hunyuan_image", ("qwen25_7b", "byt5_small")),
    Recipe(1, "longcat_image", ("qwen25_7b",)),
    Recipe(2, "kandinsky5", ("qwen25_7b", "clip_l")),
    Recipe(2, "kandinsky5_image", ("qwen25_7b", "clip_l")),
    Recipe(1, "pixeldit", ("gemma2_2b",)),
    Recipe(1, "ovis", ("qwen3_2b",)),
    Recipe(1, "lens", ("gpt_oss_20b",)),
    Recipe(1, "ideogram4", ("qwen3_8b", "qwen3vl_8b")),
    Recipe(1, "boogu", ("qwen3vl_8b",)),
    Recipe(1, "joyimage", ("qwen3vl_8b",)),
    Recipe(1, "mage", ("qwen3vl_4b",)),
    Recipe(1, "yue2", ("yue2",)),
    # 一个文件、ComfyUI 认出是这几种之后不看 type:Anima 的官方模板就是 stable_diffusion 配 Qwen3 0.6B
    Recipe(1, ANY_TYPE, ("clip_h",), ("SD 2",)),
    Recipe(1, ANY_TYPE, ("t5_xl",), ("AuraFlow", "Pony V7")),  # Pony V7 是 AuraFlow 的结构
    Recipe(1, ANY_TYPE, ("llama3_8b",), ("HiDream",)),
    Recipe(1, ANY_TYPE, ("mistral3_24b",), ("Flux.2",)),
    Recipe(1, ANY_TYPE, ("qwen3_06b",), ("Anima",)),
    Recipe(1, ANY_TYPE, ("qwen3vl_32b",), ("MiniMax H3",)),
    Recipe(1, ANY_TYPE, ("gemma3_12b",), ("LTX-Video",)),
    Recipe(1, ANY_TYPE, ("t5_xxl_v1", "t5_gemma", "gemma3_4b", "gemma4_e2b", "gemma4_e4b", "gemma4_12b", "gemma4_31b",
                         "qwen25_3b", "qwen3_2b", "qwen35", "qwen35_08b", "qwen35_2b", "qwen35_4b", "qwen35_9b",
                         "qwen35_27b", "jina_clip_v2", "ministral3_3b", "gpt_oss_20b", "ming_image")),
)
#: 加载节点读几个文件。三个、四个的没有 type:ComfyUI 一律建 SD 3、HiDream 那一路(GGUF 的那两个带着 type 也不看)。
LOADERS = {"CLIPLoader": 1, "CLIPLoaderGGUF": 1, "DualCLIPLoader": 2, "DualCLIPLoaderGGUF": 2,
           "TripleCLIPLoader": 3, "TripleCLIPLoaderGGUF": 3, "QuadrupleCLIPLoader": 4, "QuadrupleCLIPLoaderGGUF": 4}
FIXED_TYPES = {3: "sd3", 4: "hidream"}

#: 细分的那一支(SDXL 下的 Illustrious、Wan 下的 2.2……):「常配」里排到它那一层后面
_BRANCH_FAMILIES = frozenset(one for branches in BRANCHES.values() for one in branches)


def pairs(kind: str) -> list[str]:
    """这种编码器常配哪几种底模(families.py 的家族名):按 RECIPES 的先后,细分的那一支排最后;一种都没有是空的。"""
    seen: list[str] = []
    for recipe in RECIPES:
        if kind in recipe.kinds:
            seen += [one for one in recipe.families if one not in seen]
    return sorted(seen, key=lambda one: one in _BRANCH_FAMILIES)


def applies(folder: str) -> bool:
    """这个目录放的是不是文本编码器。"""
    return folder.lower() in ENCODER_FOLDERS


def describe(folder: str, name: str, found: str | None) -> dict[str, Any] | None:
    """模型库里一个文件的那一格:不是文本编码器的目录是 None;是的话 `{kind, label, source, pairs}`。`found` 是读文件头时认出
    的种类(没读到是 None,读到了认不出是空串)。认不出也交一格(`kind` 空着),界面写「文本编码器 · 认不出是哪一种」。"""
    if not applies(folder):
        return None
    kind, source = (found, "weights") if found else (kind_of_name(name), "filename")
    if kind not in LABELS:
        return {"kind": "", "label": "", "source": "", "pairs": []}
    return {"kind": kind, "label": LABELS[kind], "source": source, "pairs": pairs(kind)}


def recipe_for(class_type: str, values: Mapping[str, Any]) -> dict[str, Any] | None:
    """工作台:选中的是 CLIP 加载节点时,按它现在的 type(`values` 是节点上下拉格子的值)说哪几种编码器在这个 type 的配方里
    (`fits`),哪几种 ComfyUI 不看 type、建出来都一样(`any_type`,不算不合)。别的种类就是不合。不是 CLIP 加载节点、
    type 是这里不认得的(更新的 ComfyUI 加的)→ None,界面不排、不标。"""
    files = LOADERS.get(class_type)
    if not files:
        return None
    wanted = FIXED_TYPES.get(files) or str(values.get("type") or "").strip()
    mine = [recipe for recipe in RECIPES if recipe.files == files]
    fits = [kind for recipe in mine if recipe.type == wanted for kind in recipe.kinds]
    if not wanted or not fits:
        return None
    loose = [kind for recipe in mine if recipe.type == ANY_TYPE for kind in recipe.kinds if kind not in fits]
    return {"type": wanted, "fits": list(dict.fromkeys(fits)), "any_type": list(dict.fromkeys(loose))}


__all__ = ["ENCODER_FOLDERS", "KINDS", "RECIPES", "applies", "describe", "kind_of_gguf", "kind_of_header", "kind_of_name",
           "kind_of_weights", "pairs", "recipe_for"]
