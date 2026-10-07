"""ComfyUI 插件的模型库:底模家族怎么认(ADR 0034 §2 及 2026-10-06 的补充)。

列出、下载那一侧钉在 test_comfyui_plugin_model_library.py;这里钉的是「认底模」:

- 权重结构(weights.py):文件头里的张量名和形状 → 家族。实录的样本来自维护者那台 ComfyUI 上的真文件(只留张量名和形状、
  按块号削短,名字换成中性的),没有实物的几种照公开的网络结构写;
- 文件头怎么读:`/pysssss/view/` 按段读(Range),地址没有、或对方不认 Range(回 200 要整个发)时只试一次、立刻挂断、
  退回 `/view_metadata`;头太大不读;GGUF 读架构名和张量表;
- 元数据、权重、文件名的先后,细分到 SDXL / Wan / Flux 的那一支;文件名的驼峰拆词和缩写(含不该认的);
- 缓存记的是原料、家族每次现推;同一个文件挂在几个目录下只列一次;「底模」不适用的目录单独标出来(文本编码器是哪一种、
  常配什么钉在 test_comfyui_plugin_text_encoders.py)。
"""

from __future__ import annotations

import json
import struct
import sys
from pathlib import Path
from typing import Any

import pytest

from app.domain.plugins import runtime
from tests.fake_comfyui import FakeComfyUI

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "bundled" / "comfyui"
ENTRY = "tools/main.py"
TOOLS = PLUGIN / "tools"
_MODULES = ("graph", "convert", "labels", "models", "run", "lines", "ws", "comfy_http", "main", "server", "service", "shared_models", "workflows",
            "tooling", "library", "sources", "install", "families", "weights", "model_files")
RECORDED = json.loads((Path(__file__).resolve().parent / "fixtures" / "comfyui" / "weight_signatures.json")
                      .read_text(encoding="utf-8"))


@pytest.fixture
def plugin():
    """插件的几个模块(families、weights、library、model_files),用完从 sys.modules 里拿掉。"""
    saved = {name: sys.modules.pop(name) for name in _MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import families
        import library
        import model_files
        import weights

        yield type("Plugin", (), {"families": families, "library": library, "weights": weights, "files": model_files})
    finally:
        sys.path.remove(str(TOOLS))
        for name in _MODULES:
            sys.modules.pop(name, None)
        sys.modules.update(saved)


@pytest.fixture
def comfy():
    with FakeComfyUI() as server:
        server.state.model_folders = {}
        yield server


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    path = tmp_path / "plugin-data"
    path.mkdir()
    return path


def _listing(server: FakeComfyUI, data_dir: Path) -> dict[str, Any]:
    return runtime.execute_tool(PLUGIN, ENTRY, "comfyui_generation", {"op": "library"}, {"SERVER_URL": server.url},
                                data_dir=data_dir, timeout=60).output


def _library(server: FakeComfyUI, data_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """列一遍,按 (目录, 名字) 索引。"""
    return {(one["folder"], one["name"]): one for one in _listing(server, data_dir)["models"]}


def _family(entry: dict[str, Any]) -> tuple[str, str]:
    return entry.get("family", ""), entry.get("family_source", "")


def _safetensors(tensors: dict[str, list[int]], meta: dict[str, str] | None = None, tail: int = 4096) -> bytes:
    """一个 safetensors 文件:8 个字节的头长度、头(JSON)、后面一截假的张量数据。"""
    header: dict[str, Any] = {"__metadata__": meta} if meta else {}
    header.update({name: {"dtype": "BF16", "shape": shape, "data_offsets": [0, 0]} for name, shape in tensors.items()})
    raw = json.dumps(header).encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw + b"\0" * tail


def _text(value: str) -> bytes:
    data = value.encode("utf-8")
    return struct.pack("<Q", len(data)) + data


def _gguf(architecture: str, tensors: dict[str, list[int]]) -> bytes:
    """一个 GGUF v3 文件头:几个键值(含一个字符串数组,解析时要跳过)、张量表(各维倒着写,最里面的一维在前)。"""
    pairs = [("general.quantization_version", 4, struct.pack("<I", 2)),
             ("tokenizer.ggml.tokens", 9, struct.pack("<IQ", 8, 2) + _text("a") + _text("b"))]
    if architecture:
        pairs.insert(0, ("general.architecture", 8, _text(architecture)))
    out = b"GGUF" + struct.pack("<IQQ", 3, len(tensors), len(pairs))
    for key, kind, value in pairs:
        out += _text(key) + struct.pack("<I", kind) + value
    for name, shape in tensors.items():
        out += _text(name) + struct.pack("<I", len(shape)) + b"".join(struct.pack("<Q", one) for one in shape[::-1])
        out += struct.pack("<IQ", 12, 0)
    return out + b"\0" * 256


def _put(server: FakeComfyUI, folder: str, name: str, body: bytes, meta: dict[str, str] | None = None) -> None:
    """一个文件:列在那个目录里,字节交给 /pysssss/view,元数据交给 /view_metadata(和头里的一致)。"""
    server.state.model_folders.setdefault(folder, []).append(name)
    server.state.model_bytes[f"{folder}/{name}"] = body
    if name.endswith(".safetensors"):
        server.state.model_metadata[f"{folder}/{name}"] = meta or {}


def _header_reads(server: FakeComfyUI) -> list[str]:
    return [path for method, path, _ in server.state.calls if method == "GET" and path.startswith("/pysssss/view/")]


def _metadata_reads(server: FakeComfyUI) -> list[str]:
    return [path for method, path, _ in server.state.calls if method == "GET" and path.startswith("/view_metadata/")]


# --- 权重结构:实录的文件头 ---------------------------------------------------------------------

@pytest.mark.parametrize("sample", RECORDED, ids=[one["name"] for one in RECORDED])
def test_权重结构_实录的文件头(plugin, sample) -> None:
    """维护者那台 ComfyUI 上的真文件(合并的大模型没有元数据、LoRA 有 kohya / diffusers / peft / ComfyUI / LyCORIS 几种
    写法、量化成 fp8 / int8 的、文本反演、IP-Adapter、ControlNet),以及认不得的(VAE、文本编码器、CLIP 视觉)。"""
    assert plugin.weights.family_of_weights(sample["tensors"]) == sample["family"], sample["note"]


def test_实录样本里每一种都有(plugin) -> None:
    found = {one["family"] for one in RECORDED}
    assert {"SD 1.5", "SDXL", "Anima", "Flux", "Flux.2", "Krea 2", "MiniMax H3", "MiniMax Music", "Qwen-Image",
            "Qwen-Image 2", "Z-Image", "Lumina", "Wan", "Wan 2.1", ""} <= found


# 这台服务器上没有实物的几种:照各家公开的网络结构写的最小样本(张量名、形状)
SYNTHETIC: list[tuple[str, dict[str, list[int]], str]] = [
    ("SD 2 的大模型:交叉注意力吃 OpenCLIP 的 1024 维", {
        "model.diffusion_model.input_blocks.1.1.transformer_blocks.0.attn2.to_k.weight": [320, 1024],
        "model.diffusion_model.input_blocks.1.1.proj_in.weight": [320, 320],
    }, "SD 2"),
    ("SD 2 的 LoRA", {"lora_unet_down_blocks_0_attentions_0_transformer_blocks_0_attn2_to_k.lora_down.weight": [8, 1024],
                     "lora_unet_down_blocks_0_attentions_0_transformer_blocks_0_attn2_to_k.lora_up.weight": [320, 8]},
     "SD 2"),
    ("SDXL 精炼模型:只有 CLIP-G,1280 维", {
        "model.diffusion_model.input_blocks.4.1.transformer_blocks.0.attn2.to_k.weight": [768, 1280]}, "SDXL"),
    ("SD 3.5(MMDiT)", {"model.diffusion_model.joint_blocks.0.context_block.attn.qkv.weight": [7296, 2432],
                       "model.diffusion_model.joint_blocks.0.x_block.attn.qkv.weight": [7296, 2432]}, "SD 3"),
    ("SD 3 的 diffusers LoRA:和 Flux 的双流块同名,宽 1536", {
        "transformer.transformer_blocks.0.attn.add_k_proj.lora_A.weight": [16, 1536],
        "transformer.transformer_blocks.0.ff_context.net.0.proj.lora_A.weight": [16, 1536]}, "SD 3"),
    ("HiDream", {"double_stream_blocks.0.block.attn1.to_q.weight": [2560, 2560],
                 "single_stream_blocks.0.block.attn1.to_q.weight": [2560, 2560]}, "HiDream"),
    ("Chroma:双流块和 Flux 一样,调制换成 distilled_guidance_layer", {
        "distilled_guidance_layer.in_proj.weight": [5120, 64],
        "double_blocks.0.img_attn.qkv.weight": [9216, 3072]}, "Chroma"),
    ("HunyuanVideo:文本先过 individual_token_refiner", {
        "model.diffusion_model.txt_in.individual_token_refiner.blocks.0.self_attn_qkv.weight": [9216, 3072],
        "model.diffusion_model.double_blocks.0.img_attn.qkv.weight": [9216, 3072]}, "HunyuanVideo"),
    ("HunyuanVideo 的 LoRA:双流块有第 20 个(编号 19),Flux 只到 18", {
        "lora_unet_double_blocks_0_img_attn_qkv.lora_down.weight": [32, 3072],
        "lora_unet_double_blocks_19_img_attn_qkv.lora_down.weight": [32, 3072]}, "HunyuanVideo"),
    ("LTX-Video:patchify_proj", {"model.diffusion_model.patchify_proj.weight": [2048, 128],
                                 "model.diffusion_model.transformer_blocks.0.attn1.to_q.weight": [2048, 2048]},
     "LTX-Video"),
    ("LTX-Video 的 LoRA:交叉注意力吃 2048 维", {
        "diffusion_model.transformer_blocks.0.attn2.to_k.lora_A.weight": [32, 2048]}, "LTX-Video"),
    ("Wan 2.2 5B:宽 3072,只有 2.2 有", {"blocks.0.self_attn.q.weight": [3072, 3072], "blocks.0.ffn.0.weight": [14336, 3072]},
     "Wan 2.2"),
    ("Wan 2.1 1.3B 的 LoRA:宽 1536,只有 2.1 有", {"diffusion_model.blocks.0.self_attn.q.lora_A.weight": [32, 1536]},
     "Wan 2.1"),
    ("Flux.2 klein 4B 的 LoRA:和 Flux.1 一样宽,单流块 linear1 是宽度的 9 倍", {
        "diffusion_model.single_blocks.0.linear1.lora_A.weight": [16, 3072],
        "diffusion_model.single_blocks.0.linear1.lora_B.weight": [27648, 16]}, "Flux.2"),
    ("Flux.1 的同一处是 7 倍", {"diffusion_model.single_blocks.0.linear1.lora_A.weight": [16, 3072],
                              "diffusion_model.single_blocks.0.linear1.lora_B.weight": [21504, 16]}, "Flux"),
    ("Flux.2 dev 只训了注意力:宽 6144", {"double_blocks.0.img_attn.qkv.lora_A.weight": [16, 6144]}, "Flux.2"),
    ("AuraFlow(Pony V7)的 diffusers LoRA:也有 single_transformer_blocks,不说成 Flux", {
        "transformer.joint_transformer_blocks.0.attn.to_q.lora_A.weight": [16, 3072],
        "transformer.single_transformer_blocks.0.attn.to_q.lora_A.weight": [16, 3072],
        "transformer.single_transformer_blocks.0.ff.linear_1.lora_A.weight": [16, 3072]}, "AuraFlow"),
    ("AuraFlow 的大模型(ComfyUI 写法)", {"model.diffusion_model.double_layers.0.attn.w1q.weight": [3072, 3072],
                                       "model.diffusion_model.single_layers.0.attn.w1q.weight": [3072, 3072]},
     "AuraFlow"),
    ("Kolors 的大模型:SDXL 的 UNet,ChatGLM 的 4096 维先投到 2048", {
        "model.diffusion_model.encoder_hid_proj.weight": [2048, 4096],
        "model.diffusion_model.input_blocks.4.1.transformer_blocks.0.attn2.to_k.weight": [640, 2048]}, "Kolors"),
    ("SD 2 的文本反演:1024 维", {"emb_params": [8, 1024]}, "SD 2"),
    ("SD 1 的 IP-Adapter", {"ip_adapter.1.to_k_ip.weight": [320, 768]}, "SD 1.5"),
    # 认不得的不猜
    ("没见过的 DiT", {"blocks.0.attn.qkv.weight": [4608, 1536], "blocks.0.mlp.fc1.weight": [6144, 1536]}, ""),
    ("Cosmos 14B:块的写法和 Anima 一样,宽 5120,不说成 Anima", {"net.blocks.0.self_attn.q_proj.weight": [5120, 5120]}, ""),
    ("LoKr 看不出宽度:只有 Wan 式的块名也只说 Wan", {"diffusion_model.blocks.0.self_attn.q.lokr_w1": [8, 8],
                                                "diffusion_model.blocks.0.self_attn.q.lokr_w2": [640, 640]}, "Wan"),
]


@pytest.mark.parametrize(("tensors", "expected"), [(one[1], one[2]) for one in SYNTHETIC], ids=[one[0] for one in SYNTHETIC])
def test_权重结构_照公开结构写的样本(plugin, tensors, expected) -> None:
    assert plugin.weights.family_of_weights(tensors) == expected


def test_LoRA只看管输入那一半的宽度(plugin) -> None:
    """up / B 那一半的第二维是秩,不是宽度:秩恰好是 768 也不该说成 SD 1。"""
    up_only = {"lora_unet_down_blocks_0_attentions_0_transformer_blocks_0_attn2_to_k.lora_up.weight": [320, 768]}
    assert plugin.weights.family_of_weights(up_only) == ""


def test_GGUF的架构名_表里认得的才认(plugin) -> None:
    family = plugin.weights.family_of_gguf
    assert (family("flux"), family("sdxl"), family("wan"), family("lumina2")) == ("Flux", "SDXL", "Wan", "Lumina")
    assert family("t5encoder") == "" and family("cosmos") == "" and family("") == "", "表里没有的不猜"


# --- 元数据、权重、文件名谁先 ----------------------------------------------------------------------

@pytest.mark.parametrize(("folder", "name", "meta", "found", "expected"), [
    # 元数据写的是训练脚本不认识的底模:规整到家族
    ("loras", "x.safetensors", {"ss_base_model_version": "anima", "modelspec.architecture": "stable-diffusion-v1/lora"},
     "", ("Anima", "metadata")),
    ("loras", "x.safetensors", {"modelspec.architecture": "anima-preview/lora"}, "", ("Anima", "metadata")),
    ("loras", "x.safetensors", {"ss_base_model_version": "krea2", "modelspec.architecture": "Krea-2/lora"}, "",
     ("Krea 2", "metadata")),
    ("loras", "x.safetensors", {"ss_base_model_version": "qwen_image_2"}, "", ("Qwen-Image 2", "metadata")),
    ("loras", "x.safetensors", {"ss_base_model_version": "Z-image turbo"}, "", ("Z-Image", "metadata")),
    ("loras", "x.safetensors", {"ss_base_model_version": "wan", "modelspec.architecture": "wan2.1/lora"}, "",
     ("Wan", "metadata")),
    # 老版 kohya:只有 ss_v2
    ("loras", "x.safetensors", {"ss_sd_model_name": "v1-5-pruned-emaonly.safetensors", "ss_v2": "False",
                                "ss_network_module": "networks.lora"}, "", ("SD 1.5", "metadata")),
    ("loras", "x.safetensors", {"ss_v2": "True", "ss_network_dim": "32"}, "", ("SD 2", "metadata")),
    ("loras", "x.safetensors", {"ss_v2": "False"}, "", ("", "")),
    # 元数据和权重对得上:用元数据(更细的也算)
    ("loras", "x.safetensors", {"ss_base_model_version": "sdxl_base_v1-0"}, "SDXL", ("SDXL", "metadata")),
    ("loras", "x.safetensors", {"modelspec.architecture": "pony"}, "SDXL", ("Pony", "metadata")),
    ("loras", "x.safetensors", {"ss_base_model_version": "wan2.2"}, "Wan", ("Wan 2.2", "metadata")),
    # 对不上架构:信权重(Flux 的 LoRA 写着 sd_1.5)
    ("loras", "x.safetensors", {"ss_base_model_version": "sd_1.5"}, "Flux", ("Flux", "weights")),
    # 元数据是表里没有的值:有权重用权重,没有就原样交出
    ("loras", "x.safetensors", {"ss_base_model_version": "mystery_v9"}, "SDXL", ("SDXL", "weights")),
    ("loras", "x.safetensors", {"ss_base_model_version": "mystery_v9"}, "", ("mystery_v9", "metadata")),
    # 权重比文件名先
    ("checkpoints", "flux_merge.safetensors", {}, "SDXL", ("SDXL", "weights")),
    # 权重说的是分不细的那一层:训练底模名、标题,再是文件名细分
    ("loras", "x.safetensors", {"ss_sd_model_name": "illustriousXL_v01.safetensors"}, "SDXL", ("Illustrious", "metadata")),
    ("loras", "x.safetensors", {"ss_sd_model_name": "889818.safetensors"}, "SDXL", ("Illustrious", "metadata")),
    ("loras", "x.safetensors", {"ss_sd_model_name": "290640.safetensors"}, "SDXL", ("Pony", "metadata")),
    ("loras", "x.safetensors", {"ss_sd_model_name": "urn:air:sdxl:checkpoint:civitai:1369089@1546777"}, "SDXL",
     ("Illustrious", "metadata")),
    ("loras", "x.safetensors", {"ss_sd_model_name": "123456789.safetensors"}, "SDXL", ("SDXL", "weights")),
    ("checkpoints", "pastelMix_ilV20.safetensors", {}, "SDXL", ("Illustrious", "filename")),
    ("loras", "style_ILL_v1.safetensors", {}, "SDXL", ("Illustrious", "filename")),
    ("diffusion_models", "wan2.2_i2v_high_noise_14B.safetensors", {}, "Wan", ("Wan 2.2", "filename")),
    ("loras", "motion_HighNoise_v2.safetensors", {}, "Wan", ("Wan 2.2", "filename")),
    ("diffusion_models", "flux1-dev-kontext_fp8.safetensors", {}, "Flux", ("Flux Kontext", "filename")),
    ("loras", "pony_style.safetensors", {}, "Flux", ("Flux", "weights")),
    ("loras", "kolors_style.safetensors", {}, "SDXL", ("Kolors", "filename")),
    ("loras", "ponyV7_style.safetensors", {}, "AuraFlow", ("Pony V7", "filename")),
    ("loras", "pony_style.safetensors", {}, "AuraFlow", ("AuraFlow", "weights")),
    ("ipadapter", "ip_adapter_plus_general_kolors.bin", {}, "", ("Kolors", "filename")),
    # 没有元数据和权重:文件名
    ("checkpoints", "Illustrious XL - v1.0_v1.0.safetensors", {}, "", ("Illustrious", "filename")),
    ("checkpoints", "v1-5.ckpt", {}, "", ("SD 1.5", "filename")),
    # 不讲底模的目录:不适用(不是「认不出」)
    ("text_encoders", "qwen3vl_4b_fp8_scaled.safetensors", {}, "", ("", "not_applicable")),
    ("upscale_models", "4x-UltraSharp.pth", {}, "", ("", "not_applicable")),
    # VOSR 2.0 超分里那个 VAE:权重认得出 Qwen-Image 的结构,可它只配 VOSR 自己用
    ("vosr2", "VOSR2/Qwen-Image-vae-2d/diffusion_pytorch_model.safetensors", {}, "Qwen-Image", ("", "not_applicable")),
    ("ultralytics_bbox", "face_yolov8m.pt", {}, "", ("", "not_applicable")),
    ("clip_gguf", "t5-v1_1-xxl-encoder-Q8_0.gguf", {"ss_base_model_version": "sdxl"}, "", ("", "not_applicable")),
    # 别的自定义目录:认不出就空着
    ("photomaker", "photomaker-v2.bin", {}, "", ("", "")),
])
def test_底模家族_元数据_权重_文件名(plugin, folder, name, meta, found, expected) -> None:
    assert plugin.families.family_of(folder, name, meta, found) == expected


@pytest.mark.parametrize(("name", "expected"), [
    # 驼峰拆开,缩写单独出现才算
    ("novaAnimeXL_ilV160.safetensors", "Illustrious"),
    ("flatbreadIL_v50.safetensors", "Illustrious"),
    ("illustrij_v21.safetensors", "Illustrious"),
    ("juggernautXL_ragnarokBy.safetensors", "SDXL"),
    ("pastelDreamXL.safetensors", "SDXL"),
    ("someMix_anima14.safetensors", "Anima"),
    ("lustrousMixAnima_v10.safetensors", "Anima"),
    ("moodyMix_zitV12.safetensors", "Z-Image"),
    ("styleMix_ZIT_v2.safetensors", "Z-Image"),
    ("krea2TurboOfficial.safetensors", "Krea 2"),
    ("Krea_2/style.safetensors", "Krea 2"),
    ("minimaxH3_int8.safetensors", "MiniMax H3"),
    ("minimax_music3_dit.safetensors", "MiniMax Music"),
    ("myStyle_qwen21.safetensors", "Qwen-Image 2"),
    ("Qwen_Image_2.1/style.safetensors", "Qwen-Image 2"),
    ("qwen_image_2512_fp8.safetensors", "Qwen-Image"),
    ("qwen_flat_color_v2.safetensors", "Qwen-Image"),
    ("HiDream-I1-dev.safetensors", "HiDream"),
    ("ImpressionismFlux.safetensors", "Flux"),
    ("flux-2-klein-4b.safetensors", "Flux.2"),
    ("hunyuan_video_t2v_720p.safetensors", "HunyuanVideo"),
    ("Chroma1-HD.safetensors", "Chroma"),
    # 不该认的
    ("animagineXL_v31.safetensors", "SDXL"),
    ("animagine-xl-3.1.safetensors", "SDXL"),
    ("animation_helper.safetensors", ""),
    ("fantasyIllustration_v2.safetensors", ""),
    ("illustrator_style.safetensors", ""),
    ("pixel_art.safetensors", ""),
    ("oil_painting.safetensors", ""),
    ("zavychromaXL_v80.safetensors", "SDXL"),
    ("influx_style.safetensors", ""),
    ("swan_lake.safetensors", ""),
    ("hunyuan_image_2.1.safetensors", ""),
    ("ill_mood.safetensors", ""),
])
def test_文件名_驼峰拆词和缩写(plugin, name, expected) -> None:
    """只看文件名时(没有元数据,也读不到文件头):`ILL`、`illu` 这种只在已经认出是 SDXL 之后才拿来细分。"""
    assert plugin.families.family_of("checkpoints", name, {}, "")[0] == expected


@pytest.mark.parametrize(("base", "expected"), [
    ("Krea 2", "Krea 2"), ("Anima", "Anima"), ("MiniMax H3", "MiniMax H3"), ("MiniMax Music 3", "MiniMax Music"),
    ("Qwen 2.1", "Qwen-Image 2"), ("Qwen 2", "Qwen-Image 2"), ("Qwen", "Qwen-Image"), ("ZImageTurbo", "Z-Image"),
    ("Wan Video 2.2 I2V-A14B", "Wan 2.2"), ("Wan Video 14B i2v 480p", "Wan 2.1"), ("Wan Video 1.3B t2v", "Wan 2.1"),
    ("Wan Video", "Wan"), ("Flux.1 D", "Flux"), ("Flux.1 Krea", "Flux"), ("Flux.1 Kontext", "Flux Kontext"),
    ("Flux.2 Klein 9B", "Flux.2"), ("Illustrious", "Illustrious"), ("NoobAI", "NoobAI"), ("Pony", "Pony"),
    ("Pony V7", "Pony V7"), ("Aura Flow", "AuraFlow"), ("SDXL 1.0", "SDXL"), ("SD 1.5", "SD 1.5"), ("SD 3.5 Large", "SD 3"),
    ("Hunyuan Video", "HunyuanVideo"), ("Hunyuan 1", "Hunyuan 1"), ("Lumina", "Lumina"),
    ("Other", ""), ("", ""), ("Kolors", "Kolors"),
])
def test_Civitai写的底模(plugin, base, expected) -> None:
    assert plugin.families.family_from_base(base) == expected


def test_不讲底模的目录(plugin) -> None:
    applies = plugin.families.family_applies
    assert not any(applies(one) for one in ("text_encoders", "clip_gguf", "clip_vision", "upscale_models", "sams",
                                            "instantid", "ultralytics", "ultralytics_bbox", "mmdets_segm", "LLM", "vosr2"))
    assert all(applies(one) for one in ("checkpoints", "loras", "diffusion_models", "unet_gguf", "vae", "photomaker"))


# --- 读文件头 -------------------------------------------------------------------------------------

SDXL_LORA = {"lora_unet_input_blocks_4_1_transformer_blocks_0_attn2_to_k.lora_down.weight": [16, 2048],
             "lora_unet_input_blocks_4_1_transformer_blocks_0_attn2_to_k.lora_up.weight": [640, 16]}
FLUX_UNET = {"double_blocks.0.img_attn.qkv.weight": [9216, 3072], "double_blocks.0.img_mod.lin.weight": [18432, 3072],
             "single_blocks.0.linear1.weight": [21504, 3072]}


def test_按段读文件头_认出权重结构(comfy, data_dir) -> None:
    _put(comfy, "loras", "merged_style.safetensors", _safetensors(SDXL_LORA))
    _put(comfy, "checkpoints", "sub\\donut_mix.safetensors", _safetensors({
        "model.diffusion_model.input_blocks.4.1.transformer_blocks.1.attn2.to_k.weight": [640, 2048],
        "conditioner.embedders.1.model.ln_final.weight": [1280]}))
    out = _library(comfy, data_dir)
    assert _family(out[("loras", "merged_style.safetensors")]) == ("SDXL", "weights")
    assert _family(out[("checkpoints", "sub\\donut_mix.safetensors")]) == ("SDXL", "weights"), "子目录(反斜杠)也读得到"
    assert all(wanted.startswith("bytes=0-") for _, wanted in comfy.state.range_requests), "每次都带 Range"
    assert not _metadata_reads(comfy), "文件头里已经有元数据,不再问 /view_metadata"


def test_头比第一段长_补读剩下的(comfy, data_dir) -> None:
    long_meta = {"ss_base_model_version": "sdxl_base_v1-0", "ss_tag_frequency": json.dumps({"1_x": {"tag": 1}}),
                 "padding": "x" * 100_000}
    _put(comfy, "loras", "long.safetensors", _safetensors(SDXL_LORA, long_meta))
    out = _library(comfy, data_dir)
    assert _family(out[("loras", "long.safetensors")]) == ("SDXL", "metadata")
    ranges = [wanted for key, wanted in comfy.state.range_requests if key == "loras/long.safetensors"]
    assert ranges[0] == "bytes=0-65535" and ranges[1].startswith("bytes=65536-") and len(ranges) == 2


def test_没有读头的地址_只试一次_退回只读元数据(comfy, data_dir) -> None:
    comfy.state.pysssss = "missing"
    meta = {"ss_base_model_version": "sdxl_base_v1-0"}
    for index in range(5):
        _put(comfy, "loras", f"style_{index}.safetensors", _safetensors(SDXL_LORA, meta), meta)
    out = _library(comfy, data_dir)
    assert len(_header_reads(comfy)) == 1, "第一个文件 404 了,别的不再试"
    assert len(_metadata_reads(comfy)) == 5
    assert _family(out[("loras", "style_0.safetensors")]) == ("SDXL", "metadata")
    # 第二次:元数据记着,还是没有那个地址 —— 试一次读头,不再问元数据
    comfy.state.calls.clear()
    _library(comfy, data_dir)
    assert len(_header_reads(comfy)) == 1 and not _metadata_reads(comfy)
    # 装上了(ComfyUI-Custom-Scripts):没认过权重的补认
    comfy.state.pysssss = "range"
    comfy.state.calls.clear()
    again = _library(comfy, data_dir)
    assert len(_header_reads(comfy)) == 5
    assert _family(again[("loras", "style_0.safetensors")]) == ("SDXL", "metadata")


def test_不认Range的_立刻挂断_不下整个文件(comfy, data_dir) -> None:
    comfy.state.pysssss = "ignore_range"
    body = _safetensors(FLUX_UNET, tail=64 * 1024 * 1024)
    _put(comfy, "diffusion_models", "big.safetensors", body)
    _put(comfy, "diffusion_models", "other.safetensors", _safetensors(FLUX_UNET))
    out = _library(comfy, data_dir)
    assert len(_header_reads(comfy)) == 1, "回了 200 就当这台没有能用的读头地址"
    assert comfy.state.range_bytes_sent < len(body) // 2, "读完响应头就挂断,没把 64 MB 都收下来"
    assert len(_metadata_reads(comfy)) == 2
    assert _family(out[("diffusion_models", "big.safetensors")]) == ("", "")


def test_头太大不读_元数据另外问_不再重试(comfy, data_dir, monkeypatch) -> None:
    huge = struct.pack("<Q", 9 * 1024 * 1024) + b"{" + b"\0" * (200 * 1024)  # 比第一段长:不限大小的话会接着读
    _put(comfy, "loras", "huge.safetensors", huge, {"ss_base_model_version": "flux1"})
    out = _library(comfy, data_dir)
    assert _family(out[("loras", "huge.safetensors")]) == ("Flux", "metadata")
    assert [wanted for _, wanted in comfy.state.range_requests] == ["bytes=0-65535"], "8 MB 以上的头不读"
    comfy.state.calls.clear()
    comfy.state.range_requests.clear()
    _library(comfy, data_dir)
    assert not comfy.state.range_requests and not _metadata_reads(comfy), "读过了(读不了也算),不再试"


def test_GGUF_读架构名和张量表(comfy, data_dir) -> None:
    _put(comfy, "unet_gguf", "zimage-Q8_0.gguf", _gguf("lumina2", {
        "layers.0.attention.qkv.weight": [11520, 3840], "cap_embedder.1.weight": [3840, 2560]}))
    _put(comfy, "unet_gguf", "mystery-Q4_K.gguf", _gguf("flux", {"some.weight": [8, 8]}))
    _put(comfy, "unet_gguf", "unknown-Q4_K.gguf", _gguf("cosmos", {"some.weight": [8, 8]}))
    _put(comfy, "clip_gguf", "t5-Q8_0.gguf", _gguf("t5encoder", {"enc.blk.0.attn_q.weight": [4096, 4096]}))
    out = _library(comfy, data_dir)
    assert _family(out[("unet_gguf", "zimage-Q8_0.gguf")]) == ("Z-Image", "weights"), "张量表比架构名(lumina2)说得细"
    assert _family(out[("unet_gguf", "mystery-Q4_K.gguf")]) == ("Flux", "weights"), "张量认不出时看架构名"
    assert _family(out[("unet_gguf", "unknown-Q4_K.gguf")]) == ("", ""), "架构名表里没有的不猜"
    assert _family(out[("clip_gguf", "t5-Q8_0.gguf")]) == ("", "not_applicable"), "文本编码器照旧不讲底模"
    assert [wanted for key, wanted in comfy.state.range_requests if key.startswith("clip_gguf/")] == ["bytes=0-65535"], \
        "文本编码器的 GGUF 只读开头那一段的键值(后面是整张词表),认是哪一种编码器(见 test_comfyui_plugin_text_encoders)"


def test_GGUF_张量表比第一段长_往后读(plugin) -> None:
    tensors = {f"double_blocks.{index}.img_attn.qkv.weight": [9216, 3072] for index in range(19)}
    tensors.update({f"single_blocks.{index}.linear1.weight{'x' * 3000}": [21504, 3072] for index in range(30)})
    body = _gguf("flux", tensors)
    assert len(body) > plugin.files.FIRST_READ

    class Ranged:
        def __init__(self) -> None:
            self.asked: list[tuple[int, int]] = []

        def get_range(self, _path: str, start: int, end: int) -> bytes:
            self.asked.append((start, end))
            return body[start:end + 1]

    source = Ranged()
    header = plugin.files.HeaderRoute(source).read("unet_gguf", "x.gguf")
    assert header.architecture == "flux" and len(header.tensors) == 49
    assert header.tensors["double_blocks.0.img_attn.qkv.weight"] == [9216, 3072], "各维倒回 PyTorch 的顺序"
    assert source.asked[0] == (0, plugin.files.FIRST_READ - 1) and len(source.asked) == 2


# --- 缓存:记原料,家族现推 ----------------------------------------------------------------------

def test_缓存记的是原料_换了规矩不用重读(plugin, comfy, data_dir) -> None:
    _put(comfy, "loras", "merged_style.safetensors", _safetensors(SDXL_LORA, {
        "ss_sd_model_name": "somethingNew.safetensors", "ss_tag_frequency": json.dumps({"1_x": {"blue": 3, "red": 9}}),
        "ss_output_name": "merged", "ss_training_comment": "x" * 2000}))
    _library(comfy, data_dir)
    saved = json.loads(next(data_dir.glob("library-*.json")).read_text(encoding="utf-8"))
    entry = next(iter(saved["files"].values()))
    assert f":{plugin.weights.DIGEST}:" in saved["version"], "权重那张表一改,版本就对不上"
    assert entry == {"meta": {"ss_sd_model_name": "somethingNew.safetensors", "ss_output_name": "merged"},
                     "tags": ["red", "blue"], "weights": "SDXL"}, "只留认底模、触发词、标题要用的几项"
    # 规矩变了(这里改的是缓存里的原料,效果一样):不重读,下次列出时现推
    entry["meta"]["ss_sd_model_name"] = "ponyDiffusionV6XL.safetensors"
    next(data_dir.glob("library-*.json")).write_text(json.dumps(saved), encoding="utf-8")
    comfy.state.calls.clear()
    out = _library(comfy, data_dir)
    assert not _header_reads(comfy) and not _metadata_reads(comfy)
    assert _family(out[("loras", "merged_style.safetensors")]) == ("Pony", "metadata")
    assert out[("loras", "merged_style.safetensors")]["triggers"] == ["red", "blue"]


def test_版本对不上的缓存整份扔掉(comfy, data_dir) -> None:
    _put(comfy, "loras", "merged_style.safetensors", _safetensors(SDXL_LORA))
    _library(comfy, data_dir)
    path = next(data_dir.glob("library-*.json"))
    files = json.loads(path.read_text(encoding="utf-8"))["files"]
    # 旧格式(记的是结论)和权重表改过之后的:都重读
    for stale in ({key: {"family": "Flux", "family_source": "metadata"} for key in files},
                  {"version": "inputs-1:000000000000", "files": {key: {"meta": {}, "weights": "Flux"} for key in files}}):
        path.write_text(json.dumps(stale), encoding="utf-8")
        comfy.state.calls.clear()
        out = _library(comfy, data_dir)
        assert len(_header_reads(comfy)) == 1
        assert _family(out[("loras", "merged_style.safetensors")]) == ("SDXL", "weights")


# --- 同一个文件挂在几个目录下 -----------------------------------------------------------------------

def test_同一个文件只列一次_留在先登记的目录(comfy, data_dir) -> None:
    state = comfy.state
    state.model_folders = {"diffusion_models": [], "text_encoders": [], "ultralytics_bbox": [], "ultralytics": [],
                           "unet_gguf": [], "clip_gguf": []}
    state.folder_paths = {
        "diffusion_models": ["C:\\comfy\\models\\unet", "C:\\comfy\\models\\diffusion_models"],
        # Windows 上路径不分大小写
        "unet_gguf": ["C:\\Comfy\\Models\\UNET", "C:\\comfy\\models\\diffusion_models"],
        "text_encoders": ["/srv/comfy/models/text_encoders"],
        "clip_gguf": ["/srv/comfy/models/./text_encoders"],
        "ultralytics_bbox": ["C:\\comfy\\models\\ultralytics\\bbox"],
        "ultralytics": ["C:\\comfy\\models\\ultralytics"],
    }
    _put(comfy, "diffusion_models", "flux_dev.safetensors", _safetensors(FLUX_UNET))
    _put(comfy, "unet_gguf", "flux_dev.safetensors", _safetensors(FLUX_UNET))
    _put(comfy, "unet_gguf", "flux_dev-Q8_0.gguf", _gguf("flux", {}))
    _put(comfy, "text_encoders", "t5xxl.safetensors", _safetensors({}))
    _put(comfy, "clip_gguf", "t5xxl.safetensors", _safetensors({}))
    _put(comfy, "ultralytics_bbox", "face.pt", b"")
    _put(comfy, "ultralytics", "bbox\\face.pt", b"")
    _put(comfy, "ultralytics", "segm\\person.pt", b"")
    listing = _listing(comfy, data_dir)
    names = sorted((one["folder"], one["name"]) for one in listing["models"])
    assert names == [("diffusion_models", "flux_dev.safetensors"), ("text_encoders", "t5xxl.safetensors"),
                     ("ultralytics", "segm\\person.pt"), ("ultralytics_bbox", "face.pt"),
                     ("unet_gguf", "flux_dev-Q8_0.gguf")]
    counts = {one["name"]: one["count"] for one in listing["folders"]}
    assert counts == {"diffusion_models": 1, "text_encoders": 1, "ultralytics_bbox": 1, "ultralytics": 1,
                      "unet_gguf": 1, "clip_gguf": 0}
    assert not [key for key, _ in comfy.state.range_requests if key.startswith("unet_gguf/flux_dev.safetensors")], \
        "重复的那一份不读"


def test_工作流按别名目录找的文件不算缺(comfy, data_dir) -> None:
    state = comfy.state
    state.model_folders = {"diffusion_models": [], "unet_gguf": []}
    state.folder_paths = {"diffusion_models": ["/m/unet"], "unet_gguf": ["/m/unet"]}
    _put(comfy, "diffusion_models", "shared.safetensors", _safetensors(FLUX_UNET))
    _put(comfy, "unet_gguf", "shared.safetensors", _safetensors(FLUX_UNET))
    state.workflows["gguf.json"] = {"nodes": [{"id": 1, "type": "UnetLoaderGGUF", "widgets_values": ["shared.safetensors"],
                                               "properties": {"models": [{"name": "shared.safetensors",
                                                                          "directory": "unet_gguf",
                                                                          "url": "https://huggingface.co/a/b/resolve/main/shared.safetensors"}]}}],
                                    "links": []}
    assert _listing(comfy, data_dir)["missing"] == []
