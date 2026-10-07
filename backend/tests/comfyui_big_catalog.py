"""一台「像真的」ComfyUI:十几张存着的工作流、几百项的 LoRA / 大模型下拉、一张一百多个可调项的图。

照维护者那台(192.168.3.15,24 张工作流、一个 LoRA 下拉 349 项、一个大模型下拉 96 项、一张没起精简表单的图 117 个可调项)
的**形状**造的 —— 选项名全是编的,不拷真实的模型清单。给预算测试和「工作台那一轮只发用得上的工作流工具」用:此前
预算测试接的假 ComfyUI 上没有一张能报成工具的工作流,工作台那一轮实际约 18 万 token,测试却一直是绿的。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "comfyui" / "agent"

#: 和维护者那台同一个量级。
LORAS = [f"style/lora_{index:03d}_v{index % 7}.safetensors" for index in range(349)]
CHECKPOINTS = [f"checkpoint_{index:03d}_xl.safetensors" for index in range(96)]
#: 普通的工作流有几张(各带三个 LoRA)。
PLAIN_WORKFLOWS = 14
#: 那张大图里串了几组「LoRA + 采样」(每组 8 个可调项)。
BIG_STAGES = 14
BIG_WORKFLOW = "放大/多段精修.json"
#: 一张名字只有一个字的(「图」):用户随口一句「出一张图」不算点了它的名。
TINY_WORKFLOW = "图.json"


def object_info() -> dict[str, Any]:
    """工作流里用到的节点定义,长下拉换成几百项。"""
    info = copy.deepcopy(json.loads((FIXTURES / "object_info.json").read_text(encoding="utf-8")))
    info["LoraLoader"]["input"]["required"]["lora_name"][0] = list(LORAS)
    info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0] = list(CHECKPOINTS)
    return info


def _sampler(model: str, positive: str, negative: str, latent: str, seed: int) -> dict[str, Any]:
    return {"class_type": "KSampler", "inputs": {"seed": seed, "steps": 20, "cfg": 6.5, "sampler_name": "euler",
                                                  "scheduler": "normal", "denoise": 1.0, "model": [model, 0],
                                                  "positive": [positive, 0], "negative": [negative, 0],
                                                  "latent_image": [latent, 0]}}


def _lora(source: str, index: int) -> dict[str, Any]:
    return {"class_type": "LoraLoader", "inputs": {"model": [source, 0], "clip": [source, 1], "lora_name": LORAS[index],
                                                    "strength_model": 0.8, "strength_clip": 0.8}}


def plain(index: int) -> dict[str, Any]:
    """一张普通的出图工作流(API 格式):大模型 → 三个 LoRA → 正反提示词 → 采样 → 解码 → 存。"""
    graph: dict[str, Any] = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CHECKPOINTS[index % len(CHECKPOINTS)]}},
        "10": _lora("4", index),
        "11": _lora("10", index + 1),
        "12": _lora("11", index + 2),
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a portrait", "clip": ["12", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry", "clip": ["12", 1]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0], "filename_prefix": f"p{index}"}},
    }
    graph["3"] = _sampler("12", "6", "7", "5", index)
    return graph


def big() -> dict[str, Any]:
    """一张没起精简表单、一百多个可调项的图:同一个大模型上串了 `BIG_STAGES` 组「LoRA + 采样」,一段接一段精修。"""
    graph: dict[str, Any] = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": CHECKPOINTS[0]}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a landscape", "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry", "clip": ["4", 1]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
    }
    latent = "5"
    for stage in range(BIG_STAGES):
        lora, sampler = str(100 + stage * 2), str(101 + stage * 2)
        graph[lora] = _lora("4", stage * 5)
        graph[sampler] = _sampler(lora, "6", "7", latent, stage)
        latent = sampler
    graph["90"] = {"class_type": "VAEDecode", "inputs": {"samples": [latent, 0], "vae": ["4", 2]}}
    graph["91"] = {"class_type": "SaveImage", "inputs": {"images": ["90", 0], "filename_prefix": "big"}}
    return graph


def workflows() -> dict[str, Any]:
    found = {f"人像/LoRA 组合 {index + 1:02d}.json": plain(index) for index in range(PLAIN_WORKFLOWS)}
    found[BIG_WORKFLOW] = big()
    found[TINY_WORKFLOW] = plain(PLAIN_WORKFLOWS)
    return found


def install(state: Any) -> None:
    """把这台「像真的」装进一个 FakeComfyUI 的状态里(替换掉默认的工作流和节点定义)。"""
    state.object_info = object_info()
    state.workflows = workflows()
