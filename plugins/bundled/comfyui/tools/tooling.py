"""**每张工作流一个工具**:它自己的提示词、它自己读素材的节点、它自己能调的参数、它自己的输出节点。

最早只有一个通用的 `run_workflow`,入参是写死的一张表(workflow / prompt / image / images / mask / values…):
它连要跑哪张工作流都不知道,表单却要人填参数 —— 放大工作流也问你要提示词。而每张工作流该收什么,图里写得
清清楚楚。所以插件在运行时把工具清单交给宿主(见 docs/PLUGIN_MANIFEST 的「运行时报出的工具」),`run_workflow`
删掉了:它能跑的每一种图(保存的工作流、粘贴的 API 模板、内置文生图)在这里都有自己的工具。

- 工具名 `wf_<12 位>`:取 ComfyUI 保存工作流时写进图里的 id(新版前端的 UUID)—— **改名、挪目录都不变**,
  工作流节点和智能体记着的名字不会因此失效;老版本存的图没有 id(或是全零的占位),退到路径的哈希(改名就是
  另一个工具);几张图撞了同一个 id(拷出来的副本),它们都退到路径的哈希;粘贴的 API 模板是 `wf_api_template`,
  内置文生图是 `wf_builtin_txt2img`;
- 入参从图里读:提示词 / 反向提示词、每个读素材的节点一格(`image_10`、`mask_11`、`video_1`…,
  `format: "asset"` 带着素材种类)、每个可调输入一格(`steps_3`、`lora_name_10`…,名字、范围、常用与否
  和生成参数同一套,见 labels);种子、尺寸、一次几张收进「高级」;
- 输出按输出节点声明(`image_9`、`video_30`、`text_40`…),外加 `asset_id` / `asset_ids` / `texts` / `summary`;
- `replaces` 告诉宿主:存着的 `run_workflow`(选的是这张工作流;那个工具已经删了)、以及这张图以前按路径哈希起的
  名字,怎么改写成这个工具 —— 宿主据此把工作流和画板上的老节点迁过来(见 domain/workflows/plugin_references),
  ComfyUI 的知识仍只在这里。

跑的时候**按当前的图重新推一遍**这些键:工作流在 ComfyUI 里改过了,认得的键照样接上,认不得的不接。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

import graph
import models
import run
from comfy_http import Comfy
from lines import ComfyError, say

TEMPLATE_TOOL = "wf_api_template"
BUILTIN_TOOL = "wf_builtin_txt2img"
#: 工具一次最多跑多久(宿主的上限就是 1800 秒)。更长的走生成(6 小时、有回执、能续等)。
TIMEOUT_SECONDS = 1800

_ROLE_LABELS = {
    "reference_image": ("图", "Image"),
    "first_frame": ("首帧", "First frame"),
    "last_frame": ("尾帧", "Last frame"),
    "mask": ("蒙版", "Mask"),
    "source_video": ("视频", "Video"),
    "driving_audio": ("驱动音频", "Driving audio"),
    "reference_audio": ("音频", "Audio"),
}
_OUTPUT_LABELS = {
    "image": ("图", "Image"),
    "video": ("视频", "Video"),
    "audio": ("音频", "Audio"),
    "text": ("文字", "Text"),
    "any": ("产出", "Output"),
}
_FEATURE_LABELS = {
    "upscale": ("放大", "upscale"),
    "inpaint": ("局部重绘", "inpainting"),
    "img2img": ("图生图", "image to image"),
    "remove-background": ("抠图", "background removal"),
    "face-restore": ("修脸", "face restore"),
    "frame-interpolation": ("补帧", "frame interpolation"),
    "controlnet": ("ControlNet", "ControlNet"),
    "lora": ("LoRA", "LoRA"),
}


def safe(node: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", str(node)).strip("_") or "0"


def output_key(media: str, node: str) -> str:
    prefix = media if media in ("image", "video", "audio", "text") else "output"
    return f"{prefix}_{safe(node)}"


def _hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def _ident_key(entry: models.Entry) -> str:
    ident = re.sub(r"[^0-9a-fA-F]", "", entry.ident).lower()
    # 全零的 UUID 是老版本前端的占位(新版前端存盘前会换掉它),不是这张图自己的 id
    return ident[:12] if len(ident) >= 12 and ident.strip("0") else ""


#: 不在 ComfyUI 里存着的那两张图:名字写死(它们没有路径,也没有 ComfyUI 给的 id)。
_FIXED_NAMES = {models.TEMPLATE: TEMPLATE_TOOL, models.BUILTIN: BUILTIN_TOOL}


def tool_names(entries: list[models.Entry]) -> dict[str, str]:
    """模型 id → 工具名。转不过来的图没有工具。

    **几张图带着同一个 id**(在 ComfyUI 外面拷了一份文件、老版本「另存为」带着原来的 id)时,它们都退到路径的
    哈希:谁拿那个 id 的名字要是按路径顺序定,新拷出来的「a 副本.json」排在前面就抢走了原来那张的名字,存着的
    工作流节点从此悄悄跑的是另一张图。宁可名字变了、调用时说「找不到」,也不张冠李戴。
    """
    counts: dict[str, int] = {}
    for entry in entries:
        key = _ident_key(entry)
        if key and not entry.problem:
            counts[key] = counts.get(key, 0) + 1
    names: dict[str, str] = {}
    for entry in entries:
        if entry.problem:
            continue
        if entry.id in _FIXED_NAMES:
            names[entry.id] = _FIXED_NAMES[entry.id]
            continue
        key = _ident_key(entry)
        names[entry.id] = f"wf_{key}" if key and counts[key] == 1 else f"wf_{_hash(entry.id)}"
    return names


def _pair(zh: str, en: str) -> dict[str, str]:
    return {"zh": zh, "en": en}


class Shape:
    """一张图推出来的工具入参,以及每个键落在图里的哪儿(跑的时候按它接回去)。"""

    def __init__(self) -> None:
        self.properties: dict[str, dict[str, Any]] = {}
        self.required: list[str] = []
        #: 键 → ("text", 角色) | ("slot", 节点, 输入名) | ("alpha_mask",) | ("param", 节点, 输入名, 类型) |
        #: ("value", 名字, 类型) | ("flag", 名字)
        self.bindings: dict[str, tuple] = {}
        self.outputs: list[str] = []
        self.output_types: dict[str, str] = {}
        self.output_labels: dict[str, dict[str, str]] = {}
        #: 老的 `run_workflow` 入参 → 这里的键(给宿主迁移存着的节点用;`values.` 开头的两种写法都有:
        #: 「节点 id.输入名」和「节点标题.输入名」)
        self.rename: dict[str, str | None] = {}
        #: 几个输出节点
        self.output_nodes = 0


def shape_of(entry: models.Entry, object_info: dict[str, Any]) -> Shape:
    api, titles = entry.api, entry.titles
    shape = Shape()
    kind = graph.kind_of(api)
    roles = graph.text_roles(api)
    placeholders = graph._placeholders_in(api)  # noqa: SLF001 — 同一个插件里的模块
    found = graph.slots(api, kind, titles)
    described = graph.describe(entry.id, entry.label, api, object_info, titles)
    required_roles = {one["role"] for one in described["inputs"] if one.get("required")}

    def alias(node: str, name: str, key: str) -> None:
        """老的 `values` 按「节点 id 或节点标题.输入名」写(见 graph.set_value):两种写法都迁到 `key` 这一格。
        标题撞了别的节点(几个节点同名、或者标题就是另一个节点的 id)时它指的不止这一处,不给别名。"""
        shape.rename[f"values.{node}.{name}"] = key
        title = titles.get(node, "")
        if title and title not in api and list(titles.values()).count(title) == 1:
            shape.rename[f"values.{title}.{name}"] = key

    if "prompt" in roles.values() or "prompt" in placeholders:
        shape.properties["prompt"] = {
            "type": "string", "x-multiline": True, "title": _pair("提示词", "Prompt"),
            "description": _pair("留空就用工作流里写好的那一句", "Leave empty to keep the workflow's own"),
        }
        shape.bindings["prompt"] = ("text", "prompt")
        shape.rename["prompt"] = "prompt"

    role_counts: dict[str, int] = {}
    for slot in found:
        role_counts[slot["role"]] = role_counts.get(slot["role"], 0) + 1
    marked: set[str] = set()
    image_slots = [slot for slot in found if slot["media"] == "image"]
    for slot in found:
        media = slot["media"]
        key = f"{'mask' if media == 'mask' else media}_{safe(slot['node'])}"
        zh, en = _ROLE_LABELS.get(slot["role"], ("素材", "Input"))
        custom = slot["title"] if slot["title"] != slot["class_type"] else ""
        if role_counts[slot["role"]] > 1 or custom:
            zh, en = f"{zh} · {custom or slot['node']}", f"{en} · {custom or slot['node']}"
        shape.properties[key] = {
            "type": "string", "format": "asset", "x-media": "image" if media == "mask" else media,
            "title": _pair(zh, en), "description": f"{slot['title']} · {slot['field']}",
        }
        shape.bindings[key] = ("slot", slot["node"], slot["field"])
        if slot["role"] in required_roles and slot["role"] not in marked:
            shape.required.append(key)
            marked.add(slot["role"])
        if media == "image":
            index = image_slots.index(slot)
            shape.rename["image" if index == 0 else f"images.{index - 1}"] = key
        elif media in ("mask", "video", "audio") and media not in shape.rename:
            shape.rename[media] = key
    consumers = graph._consumers(api)  # noqa: SLF001
    alpha = [slot for slot in image_slots
             if {used for _, _, used in consumers.get(slot["node"], [])} >= {0, 1}]
    if alpha and not any(slot["media"] == "mask" for slot in found):
        shape.properties["mask"] = {
            "type": "string", "format": "asset", "x-media": "image",
            "title": _pair("蒙版", "Mask"),
            "description": _pair(f"白色是要改的地方;替换「{alpha[0]['title']}」的 alpha 那一路",
                                 f"White marks the area to change; replaces the alpha of “{alpha[0]['title']}”"),
        }
        shape.bindings["mask"] = ("alpha_mask",)
        shape.rename["mask"] = "mask"

    if "negative" in roles.values() or "negative" in placeholders:
        shape.properties["negative_prompt"] = {
            "type": "string", "x-multiline": True, "x-advanced": True, "title": _pair("反向提示词", "Negative prompt"),
            "description": _pair("留空就用工作流里写好的那一句", "Leave empty to keep the workflow's own"),
        }
        shape.bindings["negative_prompt"] = ("text", "negative")
        shape.rename["negative_prompt"] = "negative_prompt"

    for combined, spec in graph.tunable(api, object_info, titles).items():
        node, _, name = combined.partition(".")
        key = f"{name}_{safe(node)}"
        if key in shape.properties:
            key = f"{key}_{_hash(combined)[:4]}"
        shape.properties[key] = dict(spec)
        shape.bindings[key] = ("param", node, name, spec["type"])
        alias(node, name, key)

    if "steps" in placeholders:
        # 内置文生图和粘贴的模板里的 `{{steps}}`:保存的工作流的步数是上面那样的一格参数
        shape.properties["steps"] = {
            "type": "integer", "minimum": 1, "default": models.PLACEHOLDER_DEFAULTS["steps"], "title": _pair("步数", "Steps"),
        }
        shape.bindings["steps"] = ("value", "steps", "integer")
        shape.rename["steps"] = "steps"

    seeds = graph.seed_inputs(api)
    if seeds or "seed" in placeholders:
        shape.properties["seed"] = {
            "type": "integer", "minimum": 0, "x-advanced": True, "title": _pair("随机种子", "Seed"),
            "description": _pair("留空照工作流里的设定:固定的用存着的那个,每次随机的换一个",
                                 "Leave empty to follow the workflow: a fixed seed is kept, a randomized one changes"),
        }
        shape.bindings["seed"] = ("value", "seed", "integer")
        shape.rename["seed"] = "seed"
        if len(seeds) == 1:
            alias(*seeds[0], "seed")
    sized = graph.size_node(api)
    if sized is not None or {"width", "height"} & placeholders:
        own = (api[sized]["inputs"] if sized is not None else {})
        for name, zh, en in (("width", "宽度", "Width"), ("height", "高度", "Height")):
            spec: dict[str, Any] = {"type": "integer", "minimum": 16, "x-advanced": True, "title": _pair(zh, en)}
            if isinstance(own.get(name), int):
                spec["default"] = own[name]
            shape.properties[name] = spec
            shape.bindings[name] = ("value", name, "integer")
            shape.rename[name] = name
            if sized is not None:
                alias(sized, name, name)
    batched = graph.batch_input(api)
    if batched is not None and kind == "image":
        shape.properties["num_images"] = {
            "type": "integer", "minimum": 1, "maximum": graph.MAX_BATCH, "x-advanced": True,
            "default": max(1, min(int(api[batched]["inputs"]["batch_size"]), graph.MAX_BATCH)),
            "title": _pair("张数", "Images"),
        }
        shape.bindings["num_images"] = ("value", "num_images", "integer")
    shape.properties["include_previews"] = {
        "type": "boolean", "x-advanced": True, "title": _pair("也取回预览", "Include previews"),
        "description": _pair("也取回 PreviewImage 这类预览节点的临时文件", "Also collect temporary files from preview nodes"),
    }
    shape.bindings["include_previews"] = ("flag", "include_previews")
    shape.rename["include_previews"] = "include_previews"

    nodes = graph.output_nodes(api, object_info, titles)
    shape.output_nodes = len(nodes)
    for node in nodes:
        key = output_key(node["media"], node["node"])
        zh, en = _OUTPUT_LABELS.get(node["media"], _OUTPUT_LABELS["any"])
        shape.outputs.append(key)
        shape.output_types[key] = "text" if node["media"] == "text" else ("asset" if node["media"] != "any" else "any")
        shape.output_labels[key] = _pair(f"{zh} · {node['title']}", f"{en} · {node['title']}")
    for key, data_type, zh, en in (
        ("asset_id", "asset", "第一份产出", "First output"),
        ("asset_ids", "json", "全部产出", "All outputs"),
        ("texts", "json", "文字产出", "Text outputs"),
        ("summary", "text", "摘要", "Summary"),
        ("prompt_id", "text", "任务号", "Task id"),
    ):
        shape.outputs.append(key)
        shape.output_types[key] = data_type
        shape.output_labels[key] = _pair(zh, en)
    return shape


def tool_for(entry: models.Entry, name: str, object_info: dict[str, Any]) -> dict[str, Any]:
    shape = shape_of(entry, object_info)
    label = entry.label if isinstance(entry.label, str) else entry.label.get("en", entry.id)
    label_zh = entry.label if isinstance(entry.label, str) else entry.label.get("zh", label)
    tags = [tag for tag in graph.features(entry.api) if tag in _FEATURE_LABELS]
    what_zh = "、".join(_FEATURE_LABELS[tag][0] for tag in tags)
    what_en = ", ".join(_FEATURE_LABELS[tag][1] for tag in tags)
    outputs = shape.output_nodes
    return {
        "name": name,
        "label": _pair(f"工作流 · {label_zh}", f"Workflow · {label}"),
        "description": _pair(
            f"在 ComfyUI 上原样跑「{label_zh}」这张工作流" + (f"({what_zh})" if what_zh else "")
            + f",交回它全部 {outputs} 个输出节点的产出。",
            f"Runs the ComfyUI workflow “{label}” as-is" + (f" ({what_en})" if what_en else "")
            + f" and returns everything its {outputs} output node(s) produce.",
        ),
        "stream": True,
        "timeout_seconds": TIMEOUT_SECONDS,
        # 占的是这台 ComfyUI 的显卡(常常是按时计费的云卡):智能体调它之前先问一声,和内置的生成同一档。
        "effects": "paid",
        "recommended": True,
        "input_schema": {"type": "object", "properties": shape.properties, "required": shape.required},
        "node": {"outputs": shape.outputs, "output_types": shape.output_types, "output_labels": shape.output_labels},
        "replaces": _replaces(entry, name, shape),
    }


def _replaces(entry: models.Entry, name: str, shape: Shape) -> list[dict[str, Any]]:
    """存着的哪些老节点该改写成这个工具(宿主据此迁,见 domain/workflows/plugin_references):

    - 选了这张图的通用 `run_workflow`(已经删掉的那个工具;`wait: true` 是它的默认,丢掉)。它不在了,宿主迁的时候
      把这里没有位置的几格丢掉、记进修订说明,而不是留下一个跑不起来的节点;
    - 这张图**以前按路径哈希起的名字**:老版本 ComfyUI 存的图没有 id,在新版里打开再存一次就有了,工具名跟着从
      `wf_<路径哈希>` 变成 `wf_<id>` —— 不迁的话,存着的节点从此找不到它。入参是同一张图推出来的,按同名接。
    """
    found: list[dict[str, Any]] = [
        {"tool": "run_workflow", "match": {"workflow": entry.id}, "rename": shape.rename, "drop_if": {"wait": True}},
    ]
    by_path = f"wf_{_hash(entry.id)}"
    if name != by_path and name not in _FIXED_NAMES.values():
        found.append({"tool": by_path, "match": {}, "rename": {}, "drop_if": {}})
    return found


def _cache_path(comfy: Comfy) -> Path | None:
    """工具名 → 模型 id 的对照表。**按服务器分开记**:持久目录是整个插件共用的,几台 ComfyUI 记在一个文件里就
    互相覆盖,每跑一次工具都得把那台服务器上的工作流整个重扫一遍。"""
    root = os.environ.get("MOSAEL_PLUGIN_DATA_DIR", "")
    return Path(root) / f"tools-{_hash(comfy.base)}.json" if root else None


def _remember(comfy: Comfy, names: dict[str, str]) -> None:
    path = _cache_path(comfy)
    if path is None:
        return
    try:
        path.write_text(json.dumps({tool: model_id for model_id, tool in names.items()}, ensure_ascii=False),
                        encoding="utf-8")
    except OSError:
        pass  # 记不下来只是下次要多扫一遍


def catalog(comfy: Comfy, locale: str) -> list[dict[str, Any]]:
    """`op: tools`:每张工作流(和粘贴的模板)一个工具。"""
    object_info = comfy.object_info()
    entries = list(models.each(comfy, object_info, locale))
    names = tool_names(entries)
    _remember(comfy, names)
    return [tool_for(entry, names[entry.id], object_info) for entry in entries if entry.id in names]


def _resolve(name: str, comfy: Comfy, object_info: dict[str, Any], locale: str) -> models.Entry:
    """工具名 → 那张图。先看上次记下的对照表,对不上再整个扫一遍(工作流可能刚改过名)。"""
    path = _cache_path(comfy)
    known: dict[str, str] = {}
    if path is not None and path.is_file():
        try:
            known = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            known = {}
    model_id = known.get(name)
    if model_id:
        try:
            api, _, titles = models.load(comfy, model_id, object_info, locale)
            ident = ""
            if model_id not in _FIXED_NAMES:
                ident = models._ident(comfy.fetch_workflow(model_id))  # noqa: SLF001
            entry = models.Entry(model_id, models.label_of(model_id), api, titles, "", ident)
            if tool_names([entry]).get(model_id) == name:
                return entry
        except ComfyError:
            pass
    entries = list(models.each(comfy, object_info, locale))
    names = tool_names(entries)
    _remember(comfy, names)
    for entry in entries:
        if names.get(entry.id) == name:
            return entry
    raise ComfyError(say(locale, f"ComfyUI 里已经没有这张工作流了({name})—— 到插件页点「刷新模型」",
                         f"ComfyUI no longer has this workflow ({name}). Click Refresh models on the Plugins page."))


def _typed(value: Any, kind: str) -> Any:
    """表单里填的是文字(工作流节点的配置都是字符串),按参数声明的类型转回来。"""
    if isinstance(value, str):
        text = value.strip()
        if kind == "integer":
            return int(float(text))
        if kind == "number":
            return float(text)
        if kind == "boolean":
            return text.lower() in ("true", "1", "yes", "on")
    if kind == "integer" and isinstance(value, float):
        return int(value)
    return value


def _given(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def run_tool(name: str, payload: dict[str, Any], comfy: Comfy, locale: str, emit: run.Emit) -> dict[str, Any]:
    object_info = comfy.object_info()
    entry = _resolve(name, comfy, object_info, locale)
    api, defaults, titles = models.load(comfy, entry.id, object_info, locale)
    entry = entry._replace(api=api, titles=titles)
    shape = shape_of(entry, object_info)
    kind = graph.kind_of(api)

    parameters: dict[str, Any] = {}
    overrides: dict[str, Any] = {}
    texts: dict[str, Any] = {}
    slots: dict[str, str] = {}
    alpha_mask = ""
    include_previews = False
    for key, value in payload.items():
        binding = shape.bindings.get(key)
        if binding is None or not _given(value):
            continue  # 工作流在 ComfyUI 里改过了:认不得的键不接
        how = binding[0]
        try:
            if how == "text":
                texts[binding[1]] = str(value)
            elif how == "slot":
                slots[binding[1]] = str(value)
            elif how == "alpha_mask":
                alpha_mask = str(value)
            elif how == "param":
                overrides[f"{binding[1]}.{binding[2]}"] = _typed(value, binding[3])
            elif how == "value":
                parameters[binding[1]] = _typed(value, binding[2])
            elif how == "flag":
                include_previews = bool(_typed(value, "boolean"))
        except (TypeError, ValueError) as exc:
            title = shape.properties.get(key, {}).get("title") or key
            title = title.get("zh" if locale.startswith("zh") else "en") if isinstance(title, dict) else title
            raise ComfyError(say(locale, f"「{title}」的值不对:{value}", f"“{title}” has an invalid value: {value}")) from exc

    # 跑一张存好的工作流:种子没给就用它存着的;内置图和模板的种子是占位符,照旧每次随机
    values = run.values_from(texts.get("prompt"), texts.get("negative"), parameters, defaults, keep_seed=not defaults)
    prompt = graph.fill(api, values, overrides)

    uploads = run.upload(comfy, [{"role": f"slot:{node}", "path": path} for node, path in slots.items()]
                         + ([{"role": "mask", "path": alpha_mask}] if alpha_mask else []))
    for role, names in uploads.items():
        if role == "mask":
            prompt = graph.wire_inputs(prompt, kind, {"mask": names})
            continue
        node = role.removeprefix("slot:")
        if node in prompt:
            graph.put_input(prompt, node, names[0])

    prompt_id, finished = run.run_prompt(comfy, prompt, emit, locale, titles)
    from workflows import deliver  # 避免循环 import:workflows 也用这里的 output_key

    return deliver(comfy, [(prompt_id, finished or {})], prompt, titles, locale, entry.id,
                   include_previews=include_previews, workflow=entry.id)
