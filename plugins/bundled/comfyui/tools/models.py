"""这台 ComfyUI 上有哪些「模型」—— 以及一个模型 id 背后是哪张图。

三种来源,id 各不相撞:

- `builtin:txt2img` —— 内置的最小文生图(服务器上至少有一个 checkpoint 时才有)。装好 ComfyUI、
  下好一个模型,什么工作流都没存也能用;
- `api-workflow` —— 这个连接配置里粘贴的 API 格式模板(`{{prompt}}` 等占位符照旧)。转换认不出的
  非常规工作流,总得有条退路;
- 其余 —— 用户在 ComfyUI 里**保存的每一个工作流**,id 就是它在 workflows/ 下的路径(以 `.json` 结尾)。
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Iterator, NamedTuple

import convert
import graph
from comfy_http import Comfy, is_workflow_path
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
    if not convert.is_api_graph(parsed):
        raise ComfyError(say(locale, "连接里粘贴的模板不是 API 格式(节点 id → {class_type, inputs})",
                             "The pasted template is not in API format (node id → {class_type, inputs})."))
    return parsed


def load(comfy: Comfy, model_id: str, object_info: dict[str, Any], locale: str
         ) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    """模型 id → (API 图, 占位符的默认值, 节点 id → 界面上的名字)。"""
    if model_id == BUILTIN:
        found = checkpoints(object_info)
        if not found:
            raise ComfyError(say(locale, "ComfyUI 里没有任何 checkpoint 模型 —— 先在 ComfyUI 里装一个",
                                 "ComfyUI has no checkpoint models. Install one in ComfyUI first."))
        return graph.substitute_placeholders(BUILTIN_GRAPH, {"checkpoint": found[0]}), dict(PLACEHOLDER_DEFAULTS), {}
    if model_id == TEMPLATE:
        text = template_text()
        if not text:
            raise ComfyError(say(locale, "这个连接没有粘贴 API 模板", "This connection has no API template."))
        parsed = _parse_template(text, locale)
        return parsed, dict(PLACEHOLDER_DEFAULTS), convert.titles_of(parsed)
    try:
        ui_graph = comfy.fetch_workflow(model_id)
    except ComfyError as exc:
        if exc.status == 404:
            raise ComfyError(say(locale, f"ComfyUI 里已经没有工作流「{model_id}」了 —— 到插件页点「刷新模型」,或用 list_workflows 看看现在有哪些",
                                 f"ComfyUI no longer has the workflow “{model_id}”. Click Refresh models on the Plugins page, or call list_workflows to see what exists.")) from exc
        raise
    api = convert.to_api(ui_graph, object_info, locale)
    return api, {}, convert.titles_of(api)


def label_of(path: str) -> str:
    return path[:-5] if path.endswith(".json") else path


class Entry(NamedTuple):
    """这台服务器上的一个模型(= 一张图)。"""

    id: str
    label: Any
    api: dict[str, Any]
    titles: dict[str, str]
    #: 转不过来的原因;空串 = 没问题
    problem: str
    #: ComfyUI 保存工作流时写进图里的 id(新版前端的 UUID)。**改名、挪目录都不变**,工具名靠它稳住;
    #: 老版本存的图没有,是空串。
    ident: str = ""


def _ident(ui_graph: Any) -> str:
    raw = ui_graph.get("id") if isinstance(ui_graph, dict) else None
    return raw.strip() if isinstance(raw, str) and len(raw.strip()) >= 8 else ""


def each(comfy: Comfy, object_info: dict[str, Any], locale: str) -> Iterator[Entry]:
    """这台服务器上的每个模型。

    一张图拉不下来 / 转不过来,照样交出来(带着原因)—— 目录里跳过它,`list_workflows` 把原因说出来:
    智能体问「有哪些工作流」时,一张静默消失的图比一张标着「转换失败」的图更让人摸不着头脑。
    """
    if checkpoints(object_info):
        api, _, titles = load(comfy, BUILTIN, object_info, locale)
        yield Entry(BUILTIN, {"zh": "内置文生图", "en": "Built-in text-to-image"}, api, titles, "")
    text = template_text()
    if text:
        try:
            parsed = _parse_template(text, locale)
            yield Entry(TEMPLATE, {"zh": "API 模板", "en": "API template"}, parsed, convert.titles_of(parsed), "")
        except ComfyError as exc:
            yield Entry(TEMPLATE, {"zh": "API 模板", "en": "API template"}, {}, {}, str(exc))
    for path in comfy.list_workflows():
        try:
            ui_graph = comfy.fetch_workflow(path)
            api = convert.to_api(ui_graph, object_info, locale)
        except Exception as exc:  # noqa: BLE001 — 一张图拉不下来 / 转不过来,别的照常列
            yield Entry(path, label_of(path), {}, {}, str(exc) or type(exc).__name__)
            continue
        if not api:
            yield Entry(path, label_of(path), {}, {}, say(locale, "工作流是空的", "The workflow is empty"), _ident(ui_graph))
            continue
        yield Entry(path, label_of(path), api, convert.titles_of(api), "", _ident(ui_graph))


def catalog(comfy: Comfy, locale: str) -> list[dict[str, Any]]:
    """这台服务器现在有哪些模型。一张图转不过来就跳过它,不让它拖垮整份清单。

    **不交出文件的图不是模型**(反推提示词、打标签这类只交出一段字的,见 graph.media_outputs):生成是
    「一段提示词 → 一份成片」,它们交不出成片。它们照样是工具(每张图一个,见 tooling),在工作流里、画板上用。
    """
    object_info = comfy.object_info()
    models: list[dict[str, Any]] = []
    for entry in each(comfy, object_info, locale):
        if entry.problem:
            if entry.id == TEMPLATE:
                # 模板坏了也列出来:选中它时会把「哪里坏了」说清楚。不列的话它从选择器里静默消失,
                # 用户只会以为连接没配上。
                models.append({"id": TEMPLATE, "label": entry.label, "kind": "image"})
            continue
        if not graph.media_outputs(entry.api, object_info, entry.titles):
            continue
        model = graph.describe(entry.id, entry.label, entry.api, object_info, entry.titles)
        if entry.id == BUILTIN:
            model["parameters"]["size"]["default"] = "1024x1024"
            model["prompt_dialect"] = "sd-tags"
        models.append(model)
    return models


#: 判「模型清单有没有变」时顺带看的模型目录:换了一个 checkpoint / LoRA,参数里的下拉就该跟着变。
_WATCHED_FOLDERS = ("checkpoints", "loras", "diffusion_models", "unet", "vae", "upscale_models", "controlnet")


def fingerprint(comfy: Comfy) -> str:
    """模型清单的**指纹**:保存的工作流(路径 + 大小 + 修改时间)、粘贴的模板、几个模型目录的文件名。

    宿主隔一会儿问一次(见 docs/PLUGIN_MANIFEST 的「目录变了就刷新」):指纹没变就不必把每张工作流
    重新拉一遍、转一遍。这里只列目录,不取任何一张图的内容 —— 一百张工作流也就一个请求。
    """
    digest = hashlib.sha256()
    listed = [item for item in comfy.workflow_listing() if is_workflow_path(str(item.get("path") or ""))]
    for item in sorted(listed, key=lambda one: str(one.get("path"))):
        digest.update(f"{item.get('path')}|{item.get('size')}|{item.get('modified')}\n".encode("utf-8"))
    digest.update(template_text().encode("utf-8"))
    folders = comfy.model_folders()
    for folder in sorted(set(folders or ()) & set(_WATCHED_FOLDERS)):
        digest.update(f"[{folder}]".encode("utf-8"))
        for name in sorted(comfy.models_in(folder)):
            digest.update(name.encode("utf-8") + b"\n")
    return digest.hexdigest()[:32]
