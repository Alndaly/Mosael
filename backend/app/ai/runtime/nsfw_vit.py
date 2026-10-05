"""本机识别预览图用的那个小 ViT 的一次前向(ADR 0038 §9「本地识别怎么带」):只用 numpy 和 Pillow。

模型是 Marqo/nsfw-image-detection-384 —— timm 的 `vit_tiny_patch16_384`(12 层、192 宽、3 个头、16 像素一块、输入 384),
两类(第 0 类 NSFW、第 1 类 SFW)。**不另装推理运行时**:一次前向就是十二层小注意力,照 timm 的 VisionTransformer 写一遍:
pre-norm、cls token、可学的位置编码、LayerNorm eps 1e-6、精确 GELU(erf 用 Abramowitz–Stegun 7.1.26,误差 1.5e-7,
在 float32 的精度以内),取 cls 那一格过最后的 LayerNorm 和分类头。预处理照它的 eval 变换:短边双三次缩到输入边长、居中裁、
均值 / 方差 0.5。

结构(层数、宽度、块大小、输入边长)都从权重的形状读,头数是这个架构定的(3)—— 测试用一份随机小权重的夹具(两层、24 宽、
3 个头、4 像素一块)锁住这份前向,对的数是 timm 算的。
"""

from __future__ import annotations

import json
import math
import struct
from pathlib import Path

import numpy as np
from PIL import Image

#: vit_tiny 的头数(权重形状里看不出来)
HEADS = 3
#: 分类头里 NSFW 是第几类(模型的 config.json:label_names = ["NSFW", "SFW"])
NSFW_CLASS = 0
_EPS = 1e-6
#: safetensors 头最多多大(防一份坏文件让我们读进几个 GB 的「头」)
_MAX_HEADER = 16 * 1024 * 1024


class WeightsError(ValueError):
    """权重文件读不懂(不是 safetensors、不是 float32、少了张量)。"""


def load(path: Path) -> dict[str, np.ndarray]:
    """读一份 safetensors 权重:8 字节小端的头长度、JSON 头、紧跟着的数据。只认 F32(这个模型就是 F32)。"""
    raw = path.read_bytes()
    if len(raw) < 8:
        raise WeightsError("too short")
    (length,) = struct.unpack("<Q", raw[:8])
    if length > _MAX_HEADER or 8 + length > len(raw):
        raise WeightsError("bad header length")
    try:
        header = json.loads(raw[8:8 + length])
    except ValueError as exc:
        raise WeightsError("bad header") from exc
    data = memoryview(raw)[8 + length:]
    weights: dict[str, np.ndarray] = {}
    for name, spec in header.items():
        if name == "__metadata__":
            continue
        if not isinstance(spec, dict) or spec.get("dtype") != "F32":
            raise WeightsError(f"{name}: not F32")
        start, end = spec["data_offsets"]
        shape = tuple(int(one) for one in spec["shape"])
        if not 0 <= start <= end <= len(data) or (end - start) != 4 * math.prod(shape):
            raise WeightsError(f"{name}: bad offsets")
        weights[name] = np.frombuffer(data[start:end], dtype="<f4").reshape(shape)
    for needed in ("cls_token", "pos_embed", "patch_embed.proj.weight", "norm.weight", "head.weight"):
        if needed not in weights:
            raise WeightsError(f"missing {needed}")
    return weights


def input_size(weights: dict[str, np.ndarray]) -> int:
    """输入边长:位置编码有几格(减去 cls)开方,乘块大小。"""
    patch = weights["patch_embed.proj.weight"].shape[-1]
    grid = math.isqrt(weights["pos_embed"].shape[1] - 1)
    return grid * patch


def prepare(image: Image.Image, size: int) -> np.ndarray:
    """eval 变换:短边双三次缩到 `size`(长边按比例,取整往下)、居中裁 `size`×`size`、[0,1] 再按均值 / 方差 0.5 归一。
    回 (3, size, size) 的 float32。"""
    image = image.convert("RGB")
    width, height = image.size
    if width <= height:
        target = (size, int(size * height / width))
    else:
        target = (int(size * width / height), size)
    if target != (width, height):
        image = image.resize(target, Image.Resampling.BICUBIC)
    left = int(round((target[0] - size) / 2.0))
    top = int(round((target[1] - size) / 2.0))
    image = image.crop((left, top, left + size, top + size))
    pixels = np.asarray(image, dtype=np.float32) / np.float32(255.0)
    return ((pixels - np.float32(0.5)) / np.float32(0.5)).transpose(2, 0, 1).copy()


def _layer_norm(x: np.ndarray, weight: np.ndarray, bias: np.ndarray) -> np.ndarray:
    mean = x.mean(-1, keepdims=True)
    var = ((x - mean) ** 2).mean(-1, keepdims=True)
    return (x - mean) / np.sqrt(var + np.float32(_EPS)) * weight + bias


def _erf(x: np.ndarray) -> np.ndarray:
    """Abramowitz–Stegun 7.1.26(最大误差 1.5e-7)。"""
    sign = np.sign(x)
    a = np.abs(x)
    t = 1.0 / (1.0 + 0.3275911 * a)
    poly = t * (0.254829592 + t * (-0.284496736 + t * (1.421413741 + t * (-1.453152027 + t * 1.061405429))))
    return (sign * (1.0 - poly * np.exp(-a * a))).astype(np.float32)


def _gelu(x: np.ndarray) -> np.ndarray:
    return np.float32(0.5) * x * (np.float32(1.0) + _erf(x / np.float32(math.sqrt(2.0))))


def forward(weights: dict[str, np.ndarray], pixels: np.ndarray, heads: int = HEADS) -> np.ndarray:
    """(3, H, W) 归一过的像素 → 分类头的 logits。"""
    proj = weights["patch_embed.proj.weight"]  # (dim, 3, p, p)
    dim, patch = proj.shape[0], proj.shape[-1]
    channels, height, width = pixels.shape
    grid_h, grid_w = height // patch, width // patch
    patches = pixels.reshape(channels, grid_h, patch, grid_w, patch).transpose(1, 3, 0, 2, 4)
    x = patches.reshape(grid_h * grid_w, -1) @ proj.reshape(dim, -1).T + weights["patch_embed.proj.bias"]
    x = np.concatenate([weights["cls_token"].reshape(1, dim), x], axis=0) + weights["pos_embed"].reshape(-1, dim)
    head_dim = dim // heads
    scale = np.float32(head_dim ** -0.5)
    depth = sum(1 for name in weights if name.endswith(".attn.qkv.weight"))
    tokens = x.shape[0]
    for index in range(depth):
        block = f"blocks.{index}."
        y = _layer_norm(x, weights[block + "norm1.weight"], weights[block + "norm1.bias"])
        qkv = (y @ weights[block + "attn.qkv.weight"].T + weights[block + "attn.qkv.bias"])
        q, k, v = qkv.reshape(tokens, 3, heads, head_dim).transpose(1, 2, 0, 3)
        scores = (q @ k.transpose(0, 2, 1)) * scale
        scores = np.exp(scores - scores.max(-1, keepdims=True))
        scores /= scores.sum(-1, keepdims=True)
        attended = (scores @ v).transpose(1, 0, 2).reshape(tokens, dim)
        x = x + attended @ weights[block + "attn.proj.weight"].T + weights[block + "attn.proj.bias"]
        y = _layer_norm(x, weights[block + "norm2.weight"], weights[block + "norm2.bias"])
        y = _gelu(y @ weights[block + "mlp.fc1.weight"].T + weights[block + "mlp.fc1.bias"])
        x = x + y @ weights[block + "mlp.fc2.weight"].T + weights[block + "mlp.fc2.bias"]
    x = _layer_norm(x, weights["norm.weight"], weights["norm.bias"])
    return x[0] @ weights["head.weight"].T + weights["head.bias"]


def nsfw_probability(weights: dict[str, np.ndarray], image: Image.Image) -> float:
    """这张图是 NSFW 的可能(0–1):logits 过 softmax,取 NSFW 那一类。"""
    logits = forward(weights, prepare(image, input_size(weights))).astype(np.float64)
    exp = np.exp(logits - logits.max())
    return float(exp[NSFW_CLASS] / exp.sum())
