"""ComfyUI 插件的模型库:文本编码器是哪一种、常配哪几种底模(ADR 0034 §2 的 2026-10-07 补记)。

一个文本编码器给好几种底模用(T5-XXL 给 Flux、SD 3、HiDream),所以它照旧不贴底模(`family_source` 是 not_applicable),
而是说是哪一种、常配什么。钉的是:

- 从权重认(encoders.kind_of_weights):实录的样本来自维护者那台 ComfyUI 上的 11 个真文件(只留张量名和形状、按块号削短、
  去掉量化的缩放张量),没有实物的几种照公开的网络结构写;认不出就是认不出;
- GGUF 只读开头那一段的键值(架构名、宽度、词表有几项),不往后读整张词表;
- 读不到文件头时才按文件名猜,标明是猜的;
- 「常配」照 ComfyUI 的加载规矩,家族名都是 families.py 里的;
- 工作台:CLIP 加载节点按它现在的 type 说哪几种在配方里、哪几种 ComfyUI 不看 type。
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
_MODULES = ("families", "weights", "encoders", "model_files", "comfy_http", "lines")
RECORDED = json.loads((Path(__file__).resolve().parent / "fixtures" / "comfyui" / "text_encoder_headers.json")
                      .read_text(encoding="utf-8"))


@pytest.fixture
def plugin():
    saved = {name: sys.modules.pop(name) for name in _MODULES if name in sys.modules}
    sys.path.insert(0, str(TOOLS))
    try:
        import encoders
        import families
        import model_files

        yield type("Plugin", (), {"encoders": encoders, "families": families, "files": model_files})
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


def _safetensors(tensors: dict[str, list[int]], meta: dict[str, str] | None = None) -> bytes:
    header: dict[str, Any] = {"__metadata__": meta} if meta else {}
    header.update({name: {"dtype": "BF16", "shape": shape, "data_offsets": [0, 0]} for name, shape in tensors.items()})
    raw = json.dumps(header).encode("utf-8")
    return struct.pack("<Q", len(raw)) + raw + b"\0" * 4096


def _text(value: str) -> bytes:
    data = value.encode("utf-8")
    return struct.pack("<Q", len(data)) + data


def _gguf_encoder(architecture: str, width: int, vocab: int) -> bytes:
    """一个文本编码器的 GGUF 头:架构名、那一架构的宽度和层数、一整张词表(`vocab` 个词,十几万个就比第一段长得多)、张量表。"""
    tokens = struct.pack("<IQ", 8, vocab) + _text("") * vocab
    pairs = [("general.architecture", 8, _text(architecture)),
             (f"{architecture}.embedding_length", 4, struct.pack("<I", width)),
             (f"{architecture}.block_count", 4, struct.pack("<I", 24)),
             ("tokenizer.ggml.model", 8, _text("t5")),
             ("tokenizer.ggml.tokens", 9, tokens)]
    out = b"GGUF" + struct.pack("<IQQ", 3, 1, len(pairs))
    for key, kind, value in pairs:
        out += _text(key) + struct.pack("<I", kind) + value
    out += _text("enc.blk.0.attn_q.weight") + struct.pack("<I", 2) + struct.pack("<QQ", width, width) + struct.pack("<IQ", 0, 0)
    return out + b"\0" * 256


def _put(server: FakeComfyUI, folder: str, name: str, body: bytes) -> None:
    server.state.model_folders.setdefault(folder, []).append(name)
    server.state.model_bytes[f"{folder}/{name}"] = body
    if name.endswith(".safetensors"):
        server.state.model_metadata[f"{folder}/{name}"] = {}


def _library(server: FakeComfyUI, data_dir: Path) -> dict[tuple[str, str], dict[str, Any]]:
    out = runtime.execute_tool(PLUGIN, ENTRY, "comfyui_generation", {"op": "library"}, {"SERVER_URL": server.url},
                               data_dir=data_dir, timeout=60).output
    return {(one["folder"], one["name"]): one for one in out["models"]}


# --- 从权重认 -------------------------------------------------------------------------------------

@pytest.mark.parametrize("sample", RECORDED, ids=[one["name"] for one in RECORDED])
def test_实录的文件头_认出是哪一种(plugin, sample) -> None:
    assert plugin.encoders.kind_of_weights(sample["tensors"]) == sample["kind"], sample["note"]


def _clip(layers: int, width: int, *, openclip: bool = False) -> dict[str, list[int]]:
    if openclip:
        return {f"transformer.resblocks.{index}.ln_1.weight": [width] for index in range(layers)}
    return {f"text_model.encoder.layers.{index}.mlp.fc1.weight": [width * 4, width] for index in range(layers)} | {
        "text_model.final_layer_norm.weight": [width]}


def _t5(width: int, feed: int, *, gated: bool, every_block: bool, blocks: int = 24, vocab: int = 32128) -> dict[str, list[int]]:
    out = {"shared.weight": [vocab, width], "encoder.final_layer_norm.weight": [width]}
    for index in range(blocks):
        block = f"encoder.block.{index}."
        out[block + "layer.0.SelfAttention.k.weight"] = [width, width]
        if index == 0 or every_block:
            out[block + "layer.0.SelfAttention.relative_attention_bias.weight"] = [32, 64]
        if gated:
            out[block + "layer.1.DenseReluDense.wi_0.weight"] = [feed, width]
            out[block + "layer.1.DenseReluDense.wi_1.weight"] = [feed, width]
        else:
            out[block + "layer.1.DenseReluDense.wi.weight"] = [feed, width]
    return out


def _lm(width: int, layers: int, *, prefix: str = "model.layers.", q_norm: bool = False, k_bias: bool = False,
        gemma: bool = False, v_proj: bool = True) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {"model.norm.weight": [width]}
    for index in range(layers):
        layer = f"{prefix}{index}."
        out[layer + "input_layernorm.weight"] = [width]
        out[layer + "post_attention_layernorm.weight"] = [width]
        if q_norm:
            out[layer + "self_attn.q_norm.weight"] = [128]
        if k_bias:
            out[layer + "self_attn.k_proj.bias"] = [512]
        if gemma:
            out[layer + "post_feedforward_layernorm.weight"] = [width]
        if v_proj or index % 6 != 5:
            out[layer + "self_attn.v_proj.weight"] = [1024, width]
    return out


@pytest.mark.parametrize(("tensors", "expected"), [
    (_clip(12, 768), "clip_l"),
    (_clip(24, 1024), "clip_h"),
    (_clip(32, 1280), "clip_g"),
    (_clip(32, 1280, openclip=True), "clip_g"),  # OpenCLIP 的写法
    (_clip(16, 768), ""),  # 层数对不上任何一种:不猜
    (_t5(1024, 65536, gated=False, every_block=False), "t5_xxl_v1"),
    (_t5(2048, 5120, gated=True, every_block=True), "t5_xl"),
    (_t5(2048, 5120, gated=True, every_block=False, vocab=250112), "mt5_xl"),
    (_t5(768, 3072, gated=False, every_block=False, blocks=12), "t5_base"),
    (_t5(768, 2048, gated=True, every_block=True, blocks=12, vocab=256384), "umt5_base"),
    (_t5(1472, 3584, gated=True, every_block=False, blocks=12, vocab=1510), "byt5_small"),
    (_t5(1024, 4096, gated=False, every_block=False), ""),  # T5-Large v1.0:ComfyUI 的配方里没有它
    (_lm(4096, 32), "llama3_8b"),
    (_lm(5120, 30), "mistral3_24b"),  # 给 Flux.2 削过层的也是它
    (_lm(3072, 26), "ministral3_3b"),
    (_lm(3584, 28, k_bias=True), "qwen25_7b"),
    (_lm(2048, 36, k_bias=True), "qwen25_3b"),
    (_lm(1024, 28, q_norm=True), "qwen3_06b"),
    (_lm(2560, 36, q_norm=True), "qwen3_4b"),
    (_lm(4096, 36, q_norm=True), "qwen3_8b"),
    (_lm(2560, 36, q_norm=True, prefix="model.language_model.layers."), "qwen3_4b"),
    (_lm(2304, 26, gemma=True), "gemma2_2b"),
    (_lm(3840, 48, gemma=True, q_norm=True), "gemma3_12b"),
    (_lm(3840, 48, gemma=True, q_norm=True, v_proj=False), "gemma4_12b"),  # 全局注意力层没有 v 投影
    (_lm(1536, 35, gemma=True, q_norm=True), "gemma4_e2b"),
    (_lm(2560, 42, gemma=True, q_norm=True), "gemma4_e4b"),
    (_lm(2560, 40, gemma=True, q_norm=True), ""),  # 宽度认得、层数对不上:不往 Gemma 3 4B 上靠
    (_lm(1234, 20, q_norm=True), ""),
    ({"model.language_model.layers.0.linear_attn.A_log": [16],
      "model.language_model.layers.0.input_layernorm.weight": [3000]}, "qwen35"),  # 认得是 Qwen3.5,尺寸不认得就只说到这一层
    ({"visual.deepstack_merger_list.0.norm.weight": [4608], "visual.merger.linear_fc2.weight": [3000, 4608]}, ""),
    ({"encoder.down.0.block.0.conv1.weight": [128, 3, 3, 3]}, ""),  # VAE
    ({}, ""),
])
def test_照公开结构写的样本(plugin, tensors, expected) -> None:
    assert plugin.encoders.kind_of_weights(tensors) == expected


def test_量化之后形状变了的几样不看(plugin) -> None:
    """nvfp4 把权重两个一组压进一个字节(形状只剩一半):认的时候只看归一化的向量和输出那一维。"""
    tensors = _lm(4096, 36, q_norm=True)
    tensors.update({f"model.layers.{index}.self_attn.q_proj.weight": [4096, 2048] for index in range(36)})
    assert plugin.encoders.kind_of_weights(tensors) == "qwen3_8b"


@pytest.mark.parametrize(("architecture", "sizes", "expected"), [
    ("t5encoder", {"embedding_length": 4096, "vocab": 32128}, "t5_xxl"),
    ("t5encoder", {"embedding_length": 4096, "vocab": 256384}, "umt5_xxl"),
    ("t5", {"embedding_length": 4096}, ""),  # 没有词表:分不出 T5 和 UMT5,不猜
    ("qwen3", {"embedding_length": 2560}, "qwen3_4b"),
    ("qwen2vl", {"embedding_length": 3584}, "qwen25_7b"),
    ("qwen3vl", {"embedding_length": 2560}, "qwen3vl_4b"),
    ("llama", {"embedding_length": 5120}, "mistral3_24b"),
    ("gemma3", {"embedding_length": 3840}, "gemma3_12b"),
    ("gemma3", {"embedding_length": 1000}, ""),
    ("flux", {"embedding_length": 3072}, ""),
    ("", {}, ""),
])
def test_GGUF_看架构名和键值里的尺寸(plugin, architecture, sizes, expected) -> None:
    assert plugin.encoders.kind_of_gguf(architecture, sizes) == expected


# --- 按文件名猜 -----------------------------------------------------------------------------------

@pytest.mark.parametrize(("name", "expected"), [
    ("clip_l.safetensors", "clip_l"),
    ("long_clip_l.safetensors", "clip_l"),
    ("clip_g.safetensors", "clip_g"),
    ("t5xxl_fp8_e4m3fn_scaled.safetensors", "t5_xxl"),
    ("t5-v1_1-xxl-encoder-Q8_0.gguf", "t5_xxl"),
    ("umt5_xxl_fp16.safetensors", "umt5_xxl"),
    ("oldt5_xxl_fp8_e4m3fn_scaled.safetensors", "t5_xxl_v1"),
    ("byt5_small_glyphxl_fp16.safetensors", "byt5_small"),
    ("t5gemma_b_b_ul2.safetensors", "t5_gemma"),
    ("llava_llama3_fp8_scaled.safetensors", "llama3_8b"),
    ("llama_3.1_8b_instruct_fp8_scaled.safetensors", "llama3_8b"),
    ("mistral_3_small_flux2_bf16.safetensors", "mistral3_24b"),
    ("gemma_3_12B_it.safetensors", "gemma3_12b"),
    ("gemma4_e2b_it_int8_convrot.safetensors", "gemma4_e2b"),
    ("qwen_2.5_vl_7b_fp8_scaled.safetensors", "qwen25_7b"),
    ("qwen_3_4b.safetensors", "qwen3_4b"),
    ("qwen_3_06b_base.safetensors", "qwen3_06b"),
    ("qwen_0.6b_ace15.safetensors", "qwen3_06b"),
    ("qwen3vl_4b_fp8_scaled.safetensors", "qwen3vl_4b"),
    ("sub\\qwen3vl_8b_fp8_scaled.safetensors", "qwen3vl_8b"),
    ("qwen3.5_2b_bf16.safetensors", "qwen35_2b"),
    ("jina_clip_v2_bf16.safetensors", "jina_clip_v2"),
    ("minimax_music3_text_encoder_bf16.safetensors", "minimax_music3"),
    ("qwenImage21_v21_txt_bf16.safetensors", ""),  # 名字里没有线索
    ("model.safetensors", ""),
    ("cliptext_large.safetensors", ""),
])
def test_文件名的写法(plugin, name, expected) -> None:
    assert plugin.encoders.kind_of_name(name) == expected


def test_先看权重_读不到再按文件名猜_都没有就是认不出(plugin) -> None:
    describe = plugin.encoders.describe
    assert describe("loras", "clip_l.safetensors", None) is None, "不是文本编码器的目录不交这一格"
    assert describe("text_encoders", "clip_l.safetensors", "t5_xxl")["kind"] == "t5_xxl", "权重说了算"
    assert describe("text_encoders", "clip_l.safetensors", "t5_xxl")["source"] == "weights"
    guessed = describe("clip", "clip_l.safetensors", None)
    assert (guessed["kind"], guessed["label"], guessed["source"]) == ("clip_l", "CLIP-L", "filename")
    assert describe("TEXT_ENCODERS", "clip_l.safetensors", "")["source"] == "filename", "读到了、认不出:照样按名字猜"
    assert describe("text_encoders", "mystery.safetensors", "") == {"kind": "", "label": "", "source": "", "pairs": []}


# --- 常配哪几种底模 ---------------------------------------------------------------------------------

def _family_labels(families) -> set[str]:
    labels = {label for _, label in families._META_FAMILIES} | {label for _, label in families._NAME_FAMILIES}
    labels |= {label for _, label in families._BASE_FAMILIES} | set(families.BRANCHES)
    return labels | {one for branches in families.BRANCHES.values() for one in branches}


def test_常配的家族名都是families里的_种类都登记了(plugin) -> None:
    known = _family_labels(plugin.families)
    kinds = {one.id for one in plugin.encoders.KINDS}
    for recipe in plugin.encoders.RECIPES:
        assert set(recipe.families) <= known, recipe
        assert set(recipe.kinds) <= kinds, recipe
    used = {kind for recipe in plugin.encoders.RECIPES for kind in recipe.kinds}
    assert kinds - used == {"mt5_xl"}, "每一种都在 ComfyUI 的哪个配方里(mT5-XL 只有 HunyuanDiT 的大模型自带,加载节点里没有)"
    assert plugin.encoders.ENCODER_FOLDERS <= plugin.families.NOT_APPLICABLE_FOLDERS, "底模这件事照旧不适用"


@pytest.mark.parametrize(("kind", "first"), [
    ("t5_xxl", ["Flux", "SD 3", "HiDream"]),
    ("clip_g", ["SDXL", "SD 3"]),
    ("clip_l", ["SDXL", "SD 1.5", "Flux"]),
    ("umt5_xxl", ["Wan"]),
    ("qwen25_7b", ["Qwen-Image"]),
    ("qwen3vl_4b", ["Krea 2"]),
    ("qwen3vl_8b", ["Qwen-Image 2"]),
    ("qwen3_4b", ["Z-Image", "Flux.2"]),
    ("qwen3_06b", ["Anima"]),
    ("qwen3vl_32b", ["MiniMax H3"]),
    ("minimax_music3", ["MiniMax Music"]),
    ("t5_xl", ["AuraFlow", "Pony V7"]),
    ("clip_h", ["SD 2"]),
])
def test_常配_照ComfyUI的加载规矩(plugin, kind, first) -> None:
    assert plugin.encoders.pairs(kind)[:len(first)] == first


def test_常配_细分的那一支排最后_不配的不写(plugin) -> None:
    pairs = plugin.encoders.pairs
    assert pairs("clip_l")[-4:] == ["Illustrious", "NoobAI", "Pony", "Flux Kontext"]
    assert "Kolors" not in pairs("clip_l") + pairs("clip_g"), "Kolors 的文本是 ChatGLM"
    assert "Qwen-Image" not in pairs("qwen3vl_4b"), "叫 qwen3vl_4b 的配的是 Krea 2"
    assert pairs("umt5_xxl") == ["Wan", "Wan 2.2", "Wan 2.1"]
    assert pairs("t5_xxl_v1") == [] and pairs("qwen35_9b") == [], "配的底模 Mosael 不认作家族(Cosmos)或 ComfyUI 不拿它配底模"


# --- 工作台:按节点现在的 type 排 ---------------------------------------------------------------------

def test_CLIP加载节点_按type说哪几种在配方里(plugin) -> None:
    recipe_for = plugin.encoders.recipe_for
    wan = recipe_for("CLIPLoader", {"type": "wan", "device": "default"})
    assert wan["type"] == "wan" and wan["fits"] == ["umt5_xxl"]
    assert "qwen3_06b" in wan["any_type"] and "clip_l" not in wan["any_type"], "ComfyUI 不看 type 的不算不合"
    anima = recipe_for("CLIPLoaderGGUF", {"type": "stable_diffusion"})
    assert set(anima["fits"]) == {"clip_l", "clip_h", "clip_g"}
    assert "qwen3_06b" in anima["any_type"], "Anima 的官方模板就是 stable_diffusion 配 Qwen3 0.6B"
    assert recipe_for("DualCLIPLoader", {"type": "flux"})["fits"] == ["clip_l", "t5_xxl"]
    assert recipe_for("DualCLIPLoader", {"type": "flux"})["any_type"] == [], "两个文件的每个 type 都有自己的建法"
    triple = recipe_for("TripleCLIPLoader", {})
    assert (triple["type"], set(triple["fits"])) == ("sd3", {"clip_l", "clip_g", "t5_xxl"})
    assert recipe_for("QuadrupleCLIPLoaderGGUF", {"type": "stable_diffusion"})["type"] == "hidream", "四个文件一律 HiDream"
    assert recipe_for("CLIPLoader", {"type": "some_new_type"}) is None, "不认得的 type:不排、不标"
    assert recipe_for("CLIPLoader", {}) is None
    assert recipe_for("CheckpointLoaderSimple", {"type": "wan"}) is None


def test_工作台_选文本编码器的格子带上配方(comfy) -> None:
    out = runtime.execute_tool(PLUGIN, ENTRY, "comfyui_generation", {"op": "node_folders", "nodes": [
        {"class_type": "CLIPLoader", "input": "clip_name", "values": {"type": "wan", "device": "default"}},
        {"class_type": "CLIPLoader", "input": "type", "values": {"type": "wan"}},
        {"class_type": "CLIPLoaderGGUF", "input": "clip_name", "values": {"type": "krea2"}},
        {"class_type": "CheckpointLoaderSimple", "input": "ckpt_name"},
    ]}, {"SERVER_URL": comfy.url}, timeout=60).output
    assert out["folders"] == ["text_encoders", "", "clip_gguf", "checkpoints"]
    assert out["encoders"][0]["fits"] == ["umt5_xxl"]
    assert out["encoders"][2]["fits"] == ["qwen3vl_4b"]
    assert out["encoders"][1] is None and out["encoders"][3] is None


# --- 模型库:读文件头、记原料 ------------------------------------------------------------------------

T5_XXL = next(one["tensors"] for one in RECORDED if one["kind"] == "t5_xxl")


def test_模型库_文本编码器写是哪一种和常配_底模照旧不适用(comfy, data_dir) -> None:
    _put(comfy, "text_encoders", "t5xxl_fp16.safetensors", _safetensors(T5_XXL))
    _put(comfy, "text_encoders", "mystery.safetensors", _safetensors({"something.weight": [8, 8]}))
    _put(comfy, "loras", "style.safetensors", _safetensors({"x.weight": [8, 8]}))
    out = _library(comfy, data_dir)
    t5 = out[("text_encoders", "t5xxl_fp16.safetensors")]
    assert (t5.get("family", ""), t5["family_source"]) == ("", "not_applicable")
    assert t5["encoder"] == {"kind": "t5_xxl", "label": "T5-XXL", "source": "weights",
                             "pairs": ["Flux", "SD 3", "HiDream", "LTX-Video", "Flux Kontext", "Chroma"]}
    assert out[("text_encoders", "mystery.safetensors")]["encoder"]["kind"] == "", "认不出就是认不出"
    assert "encoder" not in out[("loras", "style.safetensors")]
    saved = json.loads(next(data_dir.glob("library-*.json")).read_text(encoding="utf-8"))
    entry = next(value for key, value in saved["files"].items() if key.startswith("text_encoders\nt5xxl"))
    assert entry == {"meta": {}, "encoder": "t5_xxl"}, "记的是认成了哪一种;常配每次列出时现推"


def test_GGUF的文本编码器_只读开头那一段(comfy, data_dir) -> None:
    body = _gguf_encoder("t5encoder", 4096, 256384)
    assert len(body) > 64 * 1024, "整张词表比第一段长"
    _put(comfy, "clip_gguf", "umt5-xxl-encoder-Q8_0.gguf", body)
    _put(comfy, "clip_gguf", "mystery-Q4_K.gguf", _gguf_encoder("t5encoder", 4096, 1234))
    out = _library(comfy, data_dir)
    umt5 = out[("clip_gguf", "umt5-xxl-encoder-Q8_0.gguf")]["encoder"]
    assert (umt5["kind"], umt5["source"]) == ("umt5_xxl", "weights")
    assert out[("clip_gguf", "mystery-Q4_K.gguf")]["encoder"]["kind"] == "", "词表大小对不上:不按名字以外的猜"
    ranges = [wanted for key, wanted in comfy.state.range_requests if key == "clip_gguf/umt5-xxl-encoder-Q8_0.gguf"]
    assert ranges == ["bytes=0-65535"], "只读第一段:词表和张量表都不往后读"


def test_没有读头的地址_按文件名猜_装上之后补认(comfy, data_dir) -> None:
    comfy.state.pysssss = "missing"
    _put(comfy, "text_encoders", "clip_l.safetensors", _safetensors(T5_XXL))  # 名字说 CLIP-L,权重其实是 T5-XXL
    guessed = _library(comfy, data_dir)[("text_encoders", "clip_l.safetensors")]["encoder"]
    assert (guessed["kind"], guessed["source"]) == ("clip_l", "filename")
    comfy.state.pysssss = "range"
    again = _library(comfy, data_dir)[("text_encoders", "clip_l.safetensors")]["encoder"]
    assert (again["kind"], again["source"]) == ("t5_xxl", "weights"), "有了读头的地址,下次列出时补认,权重说了算"


def test_缓存版本带文本编码器那几张表的指纹(plugin, comfy, data_dir) -> None:
    _put(comfy, "text_encoders", "t5xxl_fp16.safetensors", _safetensors(T5_XXL))
    _library(comfy, data_dir)
    path = next(data_dir.glob("library-*.json"))
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["version"].startswith("inputs-4:") and saved["version"].endswith(":" + plugin.encoders.DIGEST)
    # 上一版的缓存(文本编码器只记了元数据):整份作废,重读文件头
    path.write_text(json.dumps({"version": "inputs-3:000000000000", "files": {
        key: {"meta": {}} for key in saved["files"]}}), encoding="utf-8")
    comfy.state.range_requests.clear()
    out = _library(comfy, data_dir)
    assert comfy.state.range_requests, "重读了"
    assert out[("text_encoders", "t5xxl_fp16.safetensors")]["encoder"]["kind"] == "t5_xxl"


def test_GGUF键值里的尺寸_词表很长也只读一段(plugin) -> None:
    body = _gguf_encoder("qwen3", 2560, 151936)

    class Ranged:
        def __init__(self) -> None:
            self.asked: list[tuple[int, int]] = []

        def get_range(self, _path: str, start: int, end: int) -> bytes:
            self.asked.append((start, end))
            return body[start:end + 1]

    source = Ranged()
    header = plugin.files.HeaderRoute(source).read("text_encoders", "qwen_3_4b-Q8_0.gguf", tensors=False)
    assert header.architecture == "qwen3" and header.tensors == {}
    assert header.sizes == {"embedding_length": 2560, "block_count": 24, "vocab": 151936}
    assert source.asked == [(0, plugin.files.FIRST_READ - 1)]
    full = plugin.files.HeaderRoute(source).read("unet_gguf", "x.gguf")
    assert full.tensors == {"enc.blk.0.attn_q.weight": [2560, 2560]}, "要张量表的照旧往后读"
