"""这台 ComfyUI 上有哪些「模型」—— 以及一个模型 id 背后是哪张图。

三种来源,id 各不相撞:

- `builtin:txt2img` —— 内置的最小文生图(服务器上至少有一个 checkpoint 时才有)。装好 ComfyUI、
  下好一个模型,什么工作流都没存也能用;
- `api-workflow` —— 这个连接配置里粘贴的 API 格式模板(`{{prompt}}` 等占位符照旧)。转换认不出的
  非常规工作流,总得有条退路;
- 其余 —— 用户在 ComfyUI 里**保存的每一个工作流**,id 就是它在 workflows/ 下的路径(以 `.json` 结尾)。
"""

from __future__ import annotations

import json
import os
from typing import Any

import graph
from comfy_http import Comfy
from lines import ComfyError, say

BUILTIN = "builtin:txt2img"
TEMPLATE = "api-workflow"

#: 最小文生图,API 格式。checkpoint 用服务器上的第一个 —— 写死一个文件名的话,除了作者那台,
#: 每一台都跑不起来。
BUILTIN_GRAPH: dict[str, Any] = {
    "3": {"class_type": "KSampler", "inputs": {
        "cfg": 7, "denoise": 1, "sampler_name": "euler", "scheduler": "normal",
        "seed": "{{seed}}", "steps": "{{steps}}",
        "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "{{checkpoint}}"}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"batch_size": 1, "width": "{{width}}", "height": "{{height}}"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": "{{prompt}}"}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["4", 1], "text": "{{negative}}"}},
    "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
    "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "mosael", "images": ["8", 0]}},
}
#: 占位符没给值时用什么(用户没动那一格)。只对内置图和粘贴的模板有意义 —— 保存的工作流有它自己的值。
PLACEHOLDER_DEFAULTS = {"negative": "", "steps": 20, "width": 1024, "height": 1024, "duration_seconds": 5}


def checkpoints(object_info: dict[str, Any]) -> list[str]:
    try:
        found = object_info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
    except (KeyError, IndexError, TypeError):
        return []
    return [str(one) for one in found] if isinstance(found, list) else []


def template_text() -> str:
    return os.environ.get("API_WORKFLOW", "").strip()


def _parse_template(text: str, locale: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except ValueError as exc:
        raise ComfyError(say(locale, "连接里粘贴的 API 模板不是合法 JSON —— 请在 ComfyUI 里用「导出 (API)」导出后再粘",
                             "The API template pasted into this connection is not valid JSON. Export it from ComfyUI with “Export (API)” and paste that.")) from exc
    if not graph.is_api_graph(parsed):
        raise ComfyError(say(locale, "连接里粘贴的模板不是 API 格式(节点 id → {class_type, inputs})",
                             "The pasted template is not in API format (node id → {class_type, inputs})."))
    return parsed


def load(comfy: Comfy, model_id: str, object_info: dict[str, Any], locale: str) -> tuple[dict[str, Any], dict[str, Any]]:
    """模型 id → (API 图, 占位符的默认值)。"""
    if model_id == BUILTIN:
        found = checkpoints(object_info)
        if not found:
            raise ComfyError(say(locale, "ComfyUI 里没有任何 checkpoint 模型 —— 先在 ComfyUI 里装一个",
                                 "ComfyUI has no checkpoint models. Install one in ComfyUI first."))
        return graph.substitute_placeholders(BUILTIN_GRAPH, {"checkpoint": found[0]}), dict(PLACEHOLDER_DEFAULTS)
    if model_id == TEMPLATE:
        text = template_text()
        if not text:
            raise ComfyError(say(locale, "这个连接没有粘贴 API 模板", "This connection has no API template."))
        return _parse_template(text, locale), dict(PLACEHOLDER_DEFAULTS)
    try:
        ui_graph = comfy.fetch_workflow(model_id)
    except ComfyError as exc:
        if exc.status == 404:
            raise ComfyError(say(locale, f"ComfyUI 里已经没有工作流「{model_id}」了 —— 到插件页点「刷新模型」",
                                 f"ComfyUI no longer has the workflow “{model_id}”. Click Refresh models on the Plugins page.")) from exc
        raise
    return graph.graph_to_api_prompt(ui_graph, object_info), {}


def _label(path: str) -> str:
    return path[:-5] if path.endswith(".json") else path


def catalog(comfy: Comfy, locale: str) -> list[dict[str, Any]]:
    """这台服务器现在有哪些模型。一张图转不过来就跳过它,不让它拖垮整份清单。"""
    object_info = comfy.object_info()
    models: list[dict[str, Any]] = []
    if checkpoints(object_info):
        api, _ = load(comfy, BUILTIN, object_info, locale)
        builtin = graph.describe(BUILTIN, {"zh": "内置文生图", "en": "Built-in text-to-image"}, api, object_info)
        builtin["parameters"]["size"]["default"] = "1024x1024"
        builtin["prompt_dialect"] = "sd-tags"
        models.append(builtin)
    text = template_text()
    if text:
        try:
            parsed = _parse_template(text, locale)
            models.append(graph.describe(TEMPLATE, {"zh": "API 模板", "en": "API template"}, parsed, object_info,
                                         graph.ui_titles(parsed)))
        except ComfyError:
            # 模板坏了也列出来:选中它时会把「哪里坏了」说清楚。不列的话它从选择器里静默消失,
            # 用户只会以为连接没配上。
            models.append({"id": TEMPLATE, "label": {"zh": "API 模板", "en": "API template"}, "kind": "image"})
    for path in comfy.list_workflows():
        try:
            ui_graph = comfy.fetch_workflow(path)
            api = graph.graph_to_api_prompt(ui_graph, object_info)
        except Exception:  # noqa: BLE001 — 一张图拉不下来 / 转不过来,别的照常列
            continue
        if not api:
            continue
        models.append(graph.describe(path, _label(path), api, object_info, graph.ui_titles(ui_graph)))
    return models
