"""从权重结构认底模(ADR 0034 §2「从权重结构认出」):文件头里的张量名和形状 → 底模家族。

为什么认得出:每种底模的网络各有各的部件和尺寸 —— SD 1.x 的交叉注意力吃 768 维的文本特征、SDXL 吃 2048 维;Flux 有
double_blocks / single_blocks 两种块;Wan 的块里是 self_attn.q 和 ffn.0。LoRA 存的是同一批层上的增量,层名照抄底模(外面
套一层 `lora_unet_` / `diffusion_model.` / `transformer.`),所以大模型、UNet、LoRA 用同一张表。

这张表是照各家公开的网络结构、对着实际文件写的(看部件名、量维度),不是照搬 ComfyUI 的 model_detection.py。

规矩:

- 张量名先规整:去掉外层包装、点换成下划线、小写 —— `model.diffusion_model.double_blocks.0.img_attn.qkv.weight` 和
  `lora_unet_double_blocks_0_img_attn_qkv.lora_down.weight` 都从 `double_blocks_0_img_attn_qkv_` 开头;
- 表从上往下认,认到为止:有独门部件的排前面,只能靠维度分的排后面;
- 分不清的少说:Wan 14B 的 2.1 和 2.2 结构一样,就说 Wan;不说错。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class Signature:
    """规整后的张量名里有一个对得上 `pattern`(给了维度的,维度也对得上)就是 `family`。"""

    family: str
    pattern: str
    #: 那个张量的输入维度得是其中之一:矩阵的第二维;LoRA 看 down / A 那一半(它的第二维就是原层的输入)
    inputs: tuple[int, ...] = ()
    #: 输出维度:矩阵的第一维;LoRA 看 up / B 那一半
    outputs: tuple[int, ...] = ()


#: SD 系 UNet 里装注意力的那几段(原版和 diffusers 两种叫法)
_UNET = r"^(?:input_blocks|output_blocks|middle_block|down_blocks|up_blocks|mid_block)_"
#: Wan、Anima(Cosmos)、Krea 2、MiniMax H3 的块都叫 blocks_N:各自靠块里的部件名分开。Wan 的 q / k / v / o 后面直接是
#: 权重或 LoRA 的那一截,不是 `_proj`
_WAN_ATTN = r"^blocks_\d+_(?:self|cross)_attn_[qkvo]_(?:weight|bias|lora|alpha|diff|hada|lokr|dora|oft)"

SIGNATURES: tuple[Signature, ...] = (
    # --- 文本反演(embeddings):向量的宽度就是那个底模的文本编码器 ---------------------------------
    Signature("SDXL", r"^clip_g$"),  # SDXL 的两个编码器各一份:clip_l(768)+ clip_g(1280)
    Signature("SD 1.5", r"^emb_params$", inputs=(768,)),  # CLIP ViT-L
    Signature("SD 2", r"^emb_params$", inputs=(1024,)),  # OpenCLIP ViT-H

    # --- 有独门部件的:看到就是它 -----------------------------------------------------------------
    # Krea 2:注意力里多一个 gate 投影,q / k / v / o 叫 wq / wk / wv / wo;文本那头有一段 txtfusion
    Signature("Krea 2", r"^txtfusion_|^blocks_\d+_attn_(?:gate|wq|wk|wv|wo)_"),
    # Anima:Cosmos-Predict2 的骨架,外加把 Qwen3 的输出接进来的 llm_adapter
    Signature("Anima", r"^llm_adapter_"),
    # MiniMax H3(音视频一起出):音频、视频各一个 patch 投影,时间步查表 adaln_t_table
    Signature("MiniMax H3", r"^adaln_t_table|^(?:audio|video)_patch_proj_"),
    # 它的 LoRA 只有块里的层:attn.qkv_proj / mlp.fc1 这种名字别家也用,所以连宽度(5376)一起认
    Signature("MiniMax H3", r"^(?:token_refiner_)?blocks_\d+_(?:attn_qkv_proj|mlp_fc1)_", inputs=(5376,)),
    # MiniMax Music:stable-audio 式的 diffusion_transformer,外加按层加权的条件(cond_layer_logits / scale)
    Signature("MiniMax Music", r"^cond_layer_(?:logits|scale)|^diffusion_transformer_transformer_layers_"),
    # HiDream:双流、单流两种块,块里再套一层 block
    Signature("HiDream", r"^(?:double|single)_stream_blocks_\d+_block_"),
    # SD 3 / 3.5(MMDiT):joint_blocks,每块分 context_block 和 x_block
    Signature("SD 3", r"^joint_blocks_\d+_(?:context|x)_block_"),
    # Chroma:Flux schnell 改的,把每块的调制换成一个蒸馏出来的 distilled_guidance_layer
    Signature("Chroma", r"^distilled_guidance_layer_"),
    # Flux.2:每块不再各有调制,整个模型共用 double_stream_modulation_img / _txt、single_stream_modulation
    Signature("Flux.2", r"^(?:double|single)_stream_modulation_"),
    # HunyuanVideo:块的写法学的 Flux,但文本进来先过 individual_token_refiner,MLP 叫 fc1 / fc2、调制叫 mod.linear;
    # 双流块有 20 个(Flux 只有 19 个,编号到 18)
    Signature("HunyuanVideo",
              r"^txt_in_individual_token_refiner_|^double_blocks_\d+_(?:img|txt)_(?:mlp_fc[12]|mod_linear)_|^double_blocks_19_"),

    # --- Flux 一系:同样是 double_blocks / single_blocks,按宽度分代 --------------------------------
    # Flux.2 dev 宽 6144、klein 9B 宽 4096(Flux.1 是 3072)
    Signature("Flux.2", r"^double_blocks_\d+_(?:img|txt)_attn_qkv_|^single_blocks_\d+_linear1_", inputs=(4096, 6144)),
    # klein 4B 和 Flux.1 一样宽 3072,但 MLP 换成了 SwiGLU:单流块 linear1 的输出是宽度的 9 倍(Flux.1 是 7 倍)
    Signature("Flux.2", r"^single_blocks_\d+_linear1_", outputs=(27648,)),
    Signature("Flux", r"^double_blocks_\d+_(?:img|txt)_(?:attn|mlp|mod)_|^single_blocks_\d+_(?:linear[12]|modulation)_"),
    # AuraFlow(Pony V7 用的结构):diffusers 写法里也有 single_transformer_blocks,但双流块叫 joint_transformer_blocks、
    # 单流块里有 ff(Flux 的单流块没有);ComfyUI 写法是 double_layers / single_layers
    Signature("AuraFlow", r"^joint_transformer_blocks_|^single_transformer_blocks_\d+_ff_|^(?:double|single)_layers_\d+_"),
    # diffusers 的写法:单流块叫 single_transformer_blocks;Flux.2 的把 qkv 和 MLP 并成一个 to_qkv_mlp_proj
    Signature("Flux.2", r"^single_transformer_blocks_\d+_attn_to_qkv_mlp_proj_"),
    Signature("Flux", r"^single_transformer_blocks_\d+_"),

    # --- Qwen-Image:diffusers 式的 transformer_blocks,图、文各一套 MLP 和调制 --------------------
    # Qwen-Image 2:宽 4096,MLP 是合在一起的 gate_up
    Signature("Qwen-Image 2", r"^transformer_blocks_\d+_(?:img|txt)_mlp_gate_up_"),
    Signature("Qwen-Image", r"^transformer_blocks_\d+_(?:img|txt)_(?:mlp|mod)_"),
    # 只训了注意力的:Qwen-Image 有 60 块,编号 19 往上的就不是 Flux(Flux 的双流块只到 18)
    Signature("Qwen-Image", r"^transformer_blocks_(?:19|[2-9]\d)_attn_(?:add_[qkv]_proj|to_[qkv])_", inputs=(3072,)),
    # diffusers 式的 Flux 双流块(ff_context、norm1_context)宽 3072;SD 3 的同名块宽 1536(medium)/ 2432(large)
    Signature("Flux", r"^transformer_blocks_\d+_(?:ff_context|norm1_context|attn_add_[qkv]_proj)_", inputs=(3072,)),
    Signature("SD 3", r"^transformer_blocks_\d+_(?:ff_context|norm1_context|attn_add_[qkv]_proj)_", inputs=(1536, 2432)),

    # --- Lumina 系(NextDiT):layers / noise_refiner / context_refiner 三段,按宽度分 -----------------
    # Z-Image 宽 3840(文本是 Qwen3 4B),它的 ControlNet(control_layers)也一样宽;Lumina 2 和照它做的 NewBie 宽 2304
    # (Civitai 也把 NewBie 记成 Lumina)
    Signature("Z-Image", r"^(?:layers|noise_refiner|context_refiner|control_layers|control_noise_refiner)_\d+_attention_"
                         r"(?:qkv|to_[qkv]|out|to_out)_", inputs=(3840,)),
    Signature("Lumina", r"^(?:layers|noise_refiner|context_refiner)_\d+_attention_|^cap_embedder_"),

    # --- Wan:blocks_N 里是 self_attn / cross_attn 的 q k v o 和 ffn.0 / ffn.2 ---------------------
    # 只有 2.1 的图生视频(和首尾帧)带 CLIP 图像那一路:cross_attn.k_img / v_img
    Signature("Wan 2.1", r"^blocks_\d+_cross_attn_[kv]_img_"),
    # 宽度分得出的:1.3B 宽 1536(只有 2.1 有),5B 宽 3072(只有 2.2 有);14B 宽 5120,两代都有,只说 Wan
    Signature("Wan 2.1", _WAN_ATTN, inputs=(1536,)),
    Signature("Wan 2.2", _WAN_ATTN, inputs=(3072,)),
    Signature("Wan", _WAN_ATTN + r"|^blocks_\d+_ffn_[02]_"),

    # --- Anima 的 LoRA:Cosmos-Predict2 2B 的块(q_proj / output_proj、mlp.layer1、三组 adaln_modulation),宽 2048。
    #     同样大小的 Cosmos LoRA 几乎只有 Anima 一家,14B 的 Cosmos 宽 5120,不在这里 ---------------
    Signature("Anima", r"^blocks_\d+_(?:self_attn_[qkv]_proj|mlp_layer1)_", inputs=(2048,)),

    # --- LTX-Video:patchify_proj 是它独有的;LoRA 看交叉注意力吃的文本宽度(2B 是 2048,13B 是 4096) --
    Signature("LTX-Video", r"^patchify_proj_"),
    Signature("LTX-Video", r"^transformer_blocks_\d+_attn2_to_[kv]_", inputs=(2048, 4096)),

    # --- Kolors:SDXL 的 UNet,文本换成 ChatGLM(4096 维),先过一层 encoder_hid_proj 投到 2048 ----------------
    Signature("Kolors", r"^encoder_hid_proj_weight$", inputs=(4096,)),

    # --- SD 系 UNet:交叉注意力 attn2 的 to_k / to_v 吃的是文本编码器的宽度 ----------------------------
    Signature("SDXL", _UNET + r"\S*attn2_to_[kv]_", inputs=(2048, 1280)),  # CLIP-L + CLIP-G 拼起来 2048;精炼模型只有 G,1280
    Signature("SD 2", _UNET + r"\S*attn2_to_[kv]_", inputs=(1024,)),  # OpenCLIP ViT-H
    Signature("SD 1.5", _UNET + r"\S*attn2_to_[kv]_", inputs=(768,)),  # CLIP ViT-L
    # 大模型里自带的文本编码器:SDXL 的两个装在 conditioner 里,SD 2 的 OpenCLIP 和 SD 1 的 CLIP 装在 cond_stage_model 里
    Signature("SDXL", r"^conditioner_embedders_1_"),
    Signature("SD 2", r"^cond_stage_model_model_transformer_"),
    Signature("SD 1.5", r"^cond_stage_model_transformer_"),
    # 没训交叉注意力的 LoRA(只训自注意力的滑块之类):SDXL 的注意力块里有好几层 transformer(编号 1 往上),SD 1 / 2 只有一层
    Signature("SDXL", _UNET + r"\S*transformer_blocks_[1-9]_"),
    # kohya 的文本编码器部分:SDXL 的第二个编码器(CLIP-G,宽 1280)叫 lora_te2_;SD 1 / 2 只有一个,叫 lora_te_
    Signature("SDXL", r"^lora_te2_", inputs=(1280,)),
    Signature("SD 1.5", r"^lora_te_", inputs=(768,)),
    Signature("SD 2", r"^lora_te_", inputs=(1024,)),
    # IP-Adapter:给每层交叉注意力加的 to_k_ip 吃的也是文本编码器的宽度
    Signature("SDXL", r"^ip_adapter_\d+_to_[kv]_ip_", inputs=(2048,)),
    Signature("SD 1.5", r"^ip_adapter_\d+_to_[kv]_ip_", inputs=(768,)),
)

#: GGUF 文件头里的 `general.architecture`(ComfyUI-GGUF 的转换脚本写的)→ 家族。张量名认不出时才看它。
GGUF_ARCHITECTURES: Mapping[str, str] = {
    "flux": "Flux", "chroma": "Chroma", "aura": "AuraFlow", "sd1": "SD 1.5", "sdxl": "SDXL", "sd3": "SD 3", "hidream": "HiDream",
    "hyvid": "HunyuanVideo", "wan": "Wan", "ltxv": "LTX-Video", "lumina2": "Lumina", "qwen_image": "Qwen-Image",
}

#: 外层的包装:大模型的 `model.diffusion_model.`、ComfyUI 格式 LoRA 的 `diffusion_model.`、diffusers / peft 的
#: `transformer.` / `unet.` / `base_model.model.`、Cosmos(Anima)原版的 `net.`、SD ControlNet 的 `control_model.`;
#: kohya 的 `lora_unet_` / `lora_transformer_`、LyCORIS 的 `lycoris_`。文本编码器那一截(`lora_te_`、`conditioner.`……)不去。
_WRAPPER = re.compile(r"^(?:model\.diffusion_model\.|diffusion_model\.|base_model\.model\.|transformer\.|unet\.|net\.|"
                      r"model\.|control_model\.|lora_unet_|lora_transformer_|lycoris_)+")
#: LoRA 里管输入那一半(down / A):它的第二维是原层的输入宽度
_DOWN = re.compile(r"_(?:lora_down|lora_a(?:_default)?)_weight$|_hada_w[12]_b$")
#: 管输出那一半(up / B):第一维是原层的输出宽度
_UP = re.compile(r"_(?:lora_up|lora_b(?:_default)?)_weight$|_hada_w[12]_a$")
#: 看不出原层宽度的(LoKr 的两个克罗内克因子、缩放、DoRA 的幅度……)
_OPAQUE = re.compile(r"_(?:lokr_\w+|alpha|dora_scale|scale|oft_\w+|diff(?:_b)?)$")

_COMPILED = tuple((one, re.compile(one.pattern)) for one in SIGNATURES)

#: 这张表的指纹:缓存里记着「这个文件的权重认成了什么」,表一改就得重认(见 library 的缓存)。
DIGEST = hashlib.sha1(repr((SIGNATURES, sorted(GGUF_ARCHITECTURES.items()))).encode("utf-8")).hexdigest()[:12]


def normalized(key: str) -> str:
    """张量名 → 规整后的样子(去包装、点换下划线、小写)。"""
    return _WRAPPER.sub("", key).replace(".", "_").lower()


def _dims(key: str, shape: Sequence[Any]) -> tuple[int | None, int | None]:
    """(输入宽度, 输出宽度);看不出的是 None。"""
    if _OPAQUE.search(key) or not shape or not all(isinstance(one, int) for one in shape):
        return None, None
    if _DOWN.search(key):
        return (shape[1] if len(shape) >= 2 else None), None
    if _UP.search(key):
        return None, shape[0]
    return (shape[1] if len(shape) >= 2 else None), shape[0]


def family_of_weights(tensors: Mapping[str, Sequence[Any]]) -> str:
    """张量名 → 形状(safetensors 文件头、GGUF 的张量表都给得出)→ 底模家族;认不出是空串。"""
    entries = [(normalized(key), list(shape) if isinstance(shape, (list, tuple)) else []) for key, shape in tensors.items()]
    for signature, pattern in _COMPILED:
        for key, shape in entries:
            if not pattern.search(key):
                continue
            if not signature.inputs and not signature.outputs:
                return signature.family
            given, made = _dims(key, shape)
            if (not signature.inputs or given in signature.inputs) and (not signature.outputs or made in signature.outputs):
                return signature.family
    return ""


def family_of_gguf(architecture: str) -> str:
    """GGUF 的 `general.architecture` → 家族;表里没有的不猜。"""
    return GGUF_ARCHITECTURES.get((architecture or "").strip().lower(), "")
