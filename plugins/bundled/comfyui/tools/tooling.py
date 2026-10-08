"""**每个入口一个工具**:它自己的提示词、它自己读素材的节点、它自己能调的参数、它自己的输出节点。一张工作流有一个完整
工作流入口和它上面每张表单各一个入口(ADR 0045,见 models.entries),各是一个工具。

最早只有一个通用的 `run_workflow`,入参是写死的一张表(workflow / prompt / image / images / mask / values…):
它连要跑哪张工作流都不知道,表单却要人填参数 —— 放大工作流也问你要提示词。而每张工作流该收什么,图里写得
清清楚楚。所以插件在运行时把工具清单交给宿主(见 docs/PLUGIN_MANIFEST 的「运行时报出的工具」),`run_workflow`
删掉了:它能跑的每一种图(保存的工作流、内置文生图)在这里都有自己的工具。

- 工具名 `wf_<12 位>`:取 ComfyUI 保存工作流时写进图里的 id(新版前端的 UUID)—— **改名、挪目录都不变**,
  工作流节点和智能体记着的名字不会因此失效;老版本存的图没有 id(或是全零的占位),退到路径的哈希(改名就是
  另一个工具);几张图撞了同一个 id(拷出来的副本),它们都退到路径的哈希;内置文生图是 `wf_builtin_txt2img`。
  这是**完整工作流**入口的名字;表单入口是它后面接 `_<表单 id>`(`wf_0ef16828a002_app`)—— 改表单标题、加减表单都不动
  别的入口的名字;
- 入参从图里读:提示词 / 反向提示词、每个读素材的节点一格(`image_10`、`mask_11`、`video_1`…,
  `format: "asset"` 带着素材种类)、每个可调输入一格(`steps_3`、`lora_name_10`…,名字、范围、常用与否
  和生成参数同一套,见 labels);种子、尺寸、跑几遍(`num_images`)收进「高级」;
- 输出按输出节点声明(`image_9`、`video_30`、`text_40`…),外加 `asset_id` / `asset_ids` / `texts` / `summary` /
  `prompt_id` —— 这五个是给工作流连线用的(第一份、全部、全部文字、摘要、任务号),声明成 `wiring_outputs`:
  画板上只落每个输出节点自己的产出(`board_outputs`),不再多出一张重复的图和几张 JSON / 摘要 / 任务号便签;
- `mirrors`:这张图**就是**模型目录里的一个模型时(交得出文件的图都是,见 graph.media_outputs),说它和哪个
  模型是同一件事、入参怎么对到生成的表单上。宿主据此在画板上只留生成那一个入口(一个概念一个入口),工作流里
  两个都在(见 _mirror);
- `workflow` 告诉宿主这个工具跑的是哪张工作流(`path` 是工作流库里的路径,内置文生图是它的模型 id;`name` 是到处同一个
  名字):宿主据此只把画布上开着的、对话里用过或点过名的那几张发给智能体(ADR 0044 修订 2026-10-08)—— 不看工具名;
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

BUILTIN_TOOL = "wf_builtin_txt2img"
#: 工具一次最多跑多久(宿主的上限就是 1800 秒)。更长的走生成(6 小时、有回执、能续等)。
TIMEOUT_SECONDS = 1800

_ROLE_LABELS = {
    "reference_image": ("图", "Image"),
    "first_frame": ("首帧", "First frame"),
    "last_frame": ("尾帧", "Last frame"),
    "mask": ("蒙版", "Mask"),
    "source_video": ("视频", "Video"),
    "reference_video": ("参考视频", "Reference video"),
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


def _ident_key(workflow: models.Workflow) -> str:
    ident = re.sub(r"[^0-9a-fA-F]", "", workflow.ident).lower()
    # 全零的 UUID 是老版本前端的占位(新版前端存盘前会换掉它),不是这张图自己的 id
    return ident[:12] if len(ident) >= 12 and ident.strip("0") else ""


#: 不在 ComfyUI 里存着的那张图(内置文生图):名字写死(它没有路径,也没有 ComfyUI 给的 id)。
_FIXED_NAMES = {models.BUILTIN: BUILTIN_TOOL}


def _workflow_names(workflows: list[models.Workflow]) -> dict[str, str]:
    """图的 id → 它的完整工作流入口的工具名。转不过来的图没有工具。

    **几张图带着同一个 id**(在 ComfyUI 外面拷了一份文件、老版本「另存为」带着原来的 id)时,它们都退到路径的
    哈希:谁拿那个 id 的名字要是按路径顺序定,新拷出来的「a 副本.json」排在前面就抢走了原来那张的名字,存着的
    工作流节点从此悄悄跑的是另一张图。宁可名字变了、调用时说「找不到」,也不张冠李戴。
    """
    counts: dict[str, int] = {}
    for workflow in workflows:
        key = _ident_key(workflow)
        if key and not workflow.problem:
            counts[key] = counts.get(key, 0) + 1
    names: dict[str, str] = {}
    for workflow in workflows:
        if workflow.problem:
            continue
        if workflow.id in _FIXED_NAMES:
            names[workflow.id] = _FIXED_NAMES[workflow.id]
            continue
        key = _ident_key(workflow)
        names[workflow.id] = f"wf_{key}" if key and counts[key] == 1 else f"wf_{_hash(workflow.id)}"
    return names


def tool_names(entries: list[models.Entry]) -> dict[str, str]:
    """入口 id(模型 id)→ 工具名。完整工作流入口是这张图的名字(见 `_workflow_names`),表单入口在它后面接 `_<表单 id>`:
    一张图退到路径哈希时,它的表单入口跟着退。撞 id 要看同一台上的每一张图,所以 `entries` 要给全。"""
    workflows = list({one.workflow.id: one.workflow for one in entries}.values())
    base = _workflow_names(workflows)
    return {one.id: f"{base[one.workflow.id]}_{one.form_id}" if one.form_id else base[one.workflow.id]
            for one in entries if one.workflow.id in base}


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
        #: 每个输出节点自己的那个输出(`image_9`、`text_40`…)—— 画板上落的就是这几个
        self.node_outputs: list[str] = []
        #: 这张图和哪个生成模型是同一件事(见 _mirror);不是的话 None
        self.mirror: dict[str, Any] | None = None
        #: 提示词写进哪几格(表单的主提示词,见 graph.Form.prompts):跑的时候只写它们
        self.prompts: dict[tuple[str, str], str] = {}
        #: 表单上读素材的槽位(见 graph.Form.slots):给的蒙版只替这几个读图节点的 alpha 那一路
        self.slots: list[dict[str, str]] = []
        #: 这个入口叫什么(主名,见 models.entries:表单标题,完整工作流是文件名)—— 工具的名字、说明用它
        self.name: Any = ""


def shape_of(entry: models.Entry, object_info: dict[str, Any]) -> Shape:
    """入参从这个入口的表单推:表单入口只有作者挑的那几项,用作者起的名字 —— 和生成说的是同一张表;完整工作流是全部
    能填的项。"""
    api, titles = entry.workflow.api, entry.workflow.titles
    shape = Shape()
    kind = graph.kind_of(api)
    form = entry.form
    shape.name = entry.name
    placeholders = graph._placeholders_in(api)  # noqa: SLF001 — 同一个插件里的模块
    #: 占位符只在内置文生图里有,它没有表单
    auto = set() if form.app else placeholders
    shape.prompts = form.prompts()
    roles = set(shape.prompts.values())
    found = shape.slots = form.slots()
    described = graph.describe(entry.id, entry.name, api, object_info, titles, form)
    required_roles = {one["role"] for one in described["inputs"] if one.get("required")}
    labelled = {(one.item["node"], one.item["input"]): one.label for one in form.fields if one.label}

    def alias(node: str, name: str, key: str) -> None:
        """老的 `values` 按「节点 id 或节点标题.输入名」写(见 graph.set_value):两种写法都迁到 `key` 这一格。
        标题撞了别的节点(几个节点同名、或者标题就是另一个节点的 id)时它指的不止这一处,不给别名。"""
        shape.rename[f"values.{node}.{name}"] = key
        title = titles.get(node, "")
        if title and title not in api and list(titles.values()).count(title) == 1:
            shape.rename[f"values.{title}.{name}"] = key

    if "prompt" in roles or "prompt" in auto:
        named = next((label for (node, name), role in shape.prompts.items()
                      if role == "prompt" and (label := labelled.get((node, name)))), "")
        shape.properties["prompt"] = {
            "type": "string", "x-multiline": True, "title": named or _pair("提示词", "Prompt"),
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
            "title": labelled.get((slot["node"], slot["field"])) or _pair(zh, en),
            "description": f"{slot['title']} · {slot['field']}",
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
    alpha = graph.alpha_masks(api, found)
    if alpha:
        shape.properties["mask"] = {
            "type": "string", "format": "asset", "x-media": "image",
            "title": _pair("蒙版", "Mask"),
            "description": _pair(f"白色是要改的地方;替换「{alpha[0]['title']}」的 alpha 那一路",
                                 f"White marks the area to change; replaces the alpha of “{alpha[0]['title']}”"),
        }
        shape.bindings["mask"] = ("alpha_mask",)
        shape.rename["mask"] = "mask"

    if "negative" in roles or "negative" in auto:
        shape.properties["negative_prompt"] = {
            "type": "string", "x-multiline": True, "x-advanced": True, "title": _pair("反向提示词", "Negative prompt"),
            "description": _pair("留空就用工作流里写好的那一句", "Leave empty to keep the workflow's own"),
        }
        shape.bindings["negative_prompt"] = ("text", "negative")
        shape.rename["negative_prompt"] = "negative_prompt"

    for field in form.parameters():
        node, name = field.item["node"], field.item["input"]
        key = f"{name}_{safe(node)}"
        if key in shape.properties:
            key = f"{key}_{_hash(field.key)[:4]}"
        spec = {"title": field.title, **field.item["schema"]}
        if field.choices is not None:
            spec["enum"] = list(field.choices)
        if form.app:
            spec.pop("x-advanced", None)  # 作者挑出来的每一项都摆在第一屏
        shape.properties[key] = spec
        shape.bindings[key] = ("param", node, name, spec["type"])
        alias(node, name, key)

    if "steps" in auto:
        # 内置文生图里的 `{{steps}}`:保存的工作流的步数是上面那样的一格参数
        shape.properties["steps"] = {
            "type": "integer", "minimum": 1, "default": models.PLACEHOLDER_DEFAULTS["steps"], "title": _pair("步数", "Steps"),
        }
        shape.bindings["steps"] = ("value", "steps", "integer")
        shape.rename["steps"] = "steps"

    seeds = graph.seed_inputs(api)
    if form.graph_item("seed"):
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
    if form.graph_item("size"):
        own = (api[sized]["inputs"] if sized is not None else {})
        for name, zh, en in (("width", "宽度", "Width"), ("height", "高度", "Height")):
            spec: dict[str, Any] = {"type": "integer", "minimum": graph.SIZE_MINIMUM, "x-advanced": True,
                                    "title": _pair(zh, en),
                                    "description": _pair("按 8 的倍数取整", "Rounded to a multiple of 8")}
            if isinstance(own.get(name), int):
                spec["default"] = own[name]
            shape.properties[name] = spec
            shape.bindings[name] = ("value", name, "integer")
            shape.rename[name] = name
            if sized is not None:
                alias(sized, name, name)
    #: 「张数」是跑几遍(graph.counts_runs),和生成那一路同一件事:每遍按工作流原样(画布上存着的 batch_size 照旧),
    #: 换一个种子,缺省一遍。键名照旧是 num_images —— 存着的工作流节点、智能体记着的入参不用改。
    if form.graph_item("runs"):
        shape.properties["num_images"] = {
            "type": "integer", "minimum": 1, "maximum": graph.MAX_RUNS, "x-advanced": True, "default": 1,
            "title": _pair("跑几遍", "Runs"),
            "description": _pair("每遍按工作流原样出图(画布上存的批量照旧),换一个种子;交回每一遍的全部产出",
                                 "Each run makes what the workflow is saved to make (its saved batch size stays) with a "
                                 "new seed; every run's outputs come back"),
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
        shape.node_outputs.append(key)
        shape.output_types[key] = "text" if node["media"] == "text" else ("asset" if node["media"] != "any" else "any")
        name = node.get("label") or {"zh": node["title"], "en": node["title"]}
        shape.output_labels[key] = _pair(f"{zh} · {name['zh']}", f"{en} · {name['en']}")
    for key, data_type, zh, en in WIRING_OUTPUTS:
        shape.outputs.append(key)
        shape.output_types[key] = data_type
        shape.output_labels[key] = _pair(zh, en)
    shape.mirror = _mirror(entry, kind, shape, found, object_info)
    return shape


#: 每张图的工具都有的那几个**给连线用的**输出:第一份(和第一个输出节点的那份是同一个文件)、全部 id、全部文字、
#: 摘要、任务号。工作流里下游接得上;画板上一个都不落(`wiring_outputs`,见 docs/PLUGIN_MANIFEST)——
#: 落的话,跑一次就在右边多出一张重复的图和几张 JSON / 摘要 / 任务号便签。
WIRING_OUTPUTS: tuple[tuple[str, str, str, str], ...] = (
    ("asset_id", "asset", "第一份产出", "First output"),
    ("asset_ids", "json", "全部产出", "All outputs"),
    ("texts", "json", "文字产出", "Text outputs"),
    ("summary", "text", "摘要", "Summary"),
    ("prompt_id", "text", "任务号", "Task id"),
)


def _mirror(entry: models.Entry, kind: str, shape: Shape, found: list[dict[str, str]],
            object_info: dict[str, Any]) -> dict[str, Any] | None:
    """这张图是不是**就是**一个生成模型:同一个 id 在插件的模型目录里(models.catalog 列它的判据:交得出文件,见
    graph.media_outputs)。是的话说出是哪一个、入参怎么对过去 —— 宿主据此在画板上只留生成那一个入口(图片 / 视频 /
    音频格的模型下拉里它就是这件事),「…」里不再列「工作流 · 名字」;工作流、智能体照旧用这个工具。

    生成那一路交得出的,就是同一件事:几个保存节点各交一份、只是中间一步的预览缺省不交(「结果取自」缺省是最终结果,
    也可以要全部或只要一个,见 graph._output_choice)、
    alpha 当蒙版有蒙版槽(graph.alpha_masks)。工具多做的 —— 交回全部输出节点、显示出来的文字、预览(「也取回预览」)——
    是给搭流程、排查的人的,留在工作流和智能体那边;**只交出一段字的图**(打标签、反推提示词)不在模型目录里,
    不是同一件事,画板上照旧是格子的一项能力。(插件 1.6.0 之前只在「一个保存节点、没有文字、没拿 alpha 当蒙版」时
    才说,两个保存节点的图于是在画板上两个入口。)

    对得过去的入参:提示词 → 提示词;读素材的节点 → 生成的素材角色,alpha 的蒙版 → 蒙版;反向提示词 / 种子 / 张数 /
    步数 / 可调参数 → 生成参数里的同一项(可调参数在生成里的键是 `节点 id.输入名`)。宽和高在生成里是一格「尺寸」,
    对不过去。
    """
    workflow = entry.workflow
    if kind not in ("image", "video", "audio") or not graph.media_outputs(workflow.api, object_info, workflow.titles):
        return None
    parameters: dict[str, str] = {}
    sources: dict[str, str] = {}
    roles = {slot["node"]: slot["role"] for slot in found}
    for key, binding in shape.bindings.items():
        how = binding[0]
        if how == "param":
            parameters[key] = f"{binding[1]}.{binding[2]}"
        elif how == "value" and binding[1] in ("seed", "num_images", "steps"):
            parameters[key] = binding[1]
        elif how == "text" and binding[1] == "negative":
            parameters[key] = "negative_prompt"
        elif how == "slot" and binding[1] in roles:
            sources[key] = roles[binding[1]]
        elif how == "alpha_mask":
            sources[key] = "mask"
    mirror: dict[str, Any] = {"generation_model": entry.id, "kind": kind}
    if "prompt" in shape.bindings:
        mirror["prompt"] = "prompt"
    if parameters:
        mirror["parameters"] = parameters
    if sources:
        mirror["sources"] = sources
    return mirror


def _said(value: Any, locale: str) -> str:
    """一个名字按语言取(文件名是一句,内置文生图是一对)。"""
    return value if isinstance(value, str) else str(value.get(locale) or value.get("en") or "")


def tool_for(entry: models.Entry, name: str, object_info: dict[str, Any]) -> dict[str, Any]:
    """一个入口的工具。**名字和模型下拉里那一项是同一个**(入口的主名):表单入口叫「工作流 · 表单标题」,完整工作流叫
    「工作流 · 文件名」。来自哪张工作流放在 `group` 里(宿主摆成第二行);说明是给模型读的,两层写在一句话里。
    改表单标题只换名字:工具名(`name`)按图里的 id 和表单 id 起,存着的节点、智能体记着的名字都不变。

    有表单的图,它的完整工作流入口**不进智能体的工具表**(`agent: false`,ADR 0045 §5):表单就是作者给别人(包括智能体)
    准备的那张表;要全部参数,智能体走生成那一路、带完整入口的模型 id。工作流节点、画板、插件页里照常有它。"""
    shape = shape_of(entry, object_info)
    workflow = entry.workflow
    label_zh, label_en = _said(shape.name, "zh"), _said(shape.name, "en")
    tags = [tag for tag in graph.features(workflow.api, object_info=object_info) if tag in _FEATURE_LABELS]
    what_zh = "、".join(_FEATURE_LABELS[tag][0] for tag in tags)
    what_en = ", ".join(_FEATURE_LABELS[tag][1] for tag in tags)
    outputs = shape.output_nodes
    if entry.form_id:
        said_zh = (f"用表单「{label_zh}」跑 ComfyUI 工作流 {workflow.id}" + (f"({what_zh})" if what_zh else "")
                   + f":只填表单上那几项,交回它全部 {outputs} 个输出节点的产出。")
        said_en = (f"Runs the ComfyUI workflow {workflow.id} through its form “{label_en}”"
                   + (f" ({what_en})" if what_en else "")
                   + f", filling in only the form's items, and returns everything its {outputs} output node(s) produce.")
    else:
        said_zh = (f"在 ComfyUI 上原样跑「{label_zh}」这张工作流" + (f"({what_zh})" if what_zh else "")
                   + ("(完整工作流:全部能填的项)" if entry.formed else "") + f",交回它全部 {outputs} 个输出节点的产出。")
        said_en = (f"Runs the ComfyUI workflow “{label_en}” as-is" + (f" ({what_en})" if what_en else "")
                   + (" (the full workflow: every fillable item)" if entry.formed else "")
                   + f" and returns everything its {outputs} output node(s) produce.")
    group = models.group_of(entry)
    return {
        "name": name,
        "label": _pair(f"工作流 · {label_zh}", f"Workflow · {label_en}"),
        "description": _pair(said_zh, said_en),
        "stream": True,
        "timeout_seconds": TIMEOUT_SECONDS,
        # 占的是这台 ComfyUI 的显卡(常常是按时计费的云卡):智能体调它之前先问一声,和内置的生成同一档。
        "effects": "paid",
        "recommended": True,
        "input_schema": {"type": "object", "properties": shape.properties, "required": shape.required},
        "node": {
            "outputs": shape.outputs, "output_types": shape.output_types, "output_labels": shape.output_labels,
            # 画板上落的是每个输出节点自己的产出;给连线用的那几个不落(见 WIRING_OUTPUTS)
            "board_outputs": shape.node_outputs,
            "wiring_outputs": [key for key, *_ in WIRING_OUTPUTS],
        },
        "replaces": _replaces(entry, name, shape),
        #: 跑的是哪张工作流(宿主据此在工作台那一轮挑工具,见模块说明):一张工作流的几个入口 `path` 相同,`name` 是各自的主名
        "workflow": {"path": workflow.id, "name": shape.name},
        **({"group": group} if group is not None else {}),
        **({"agent": False} if entry.formed and not entry.form_id else {}),
        **({"mirrors": shape.mirror} if shape.mirror else {}),
    }


def _replaces(entry: models.Entry, name: str, shape: Shape) -> list[dict[str, Any]]:
    """存着的哪些老节点该改写成这个工具(宿主据此迁,见 domain/workflows/plugin_references):

    - (完整工作流入口)选了这张图的通用 `run_workflow`(已经删掉的那个工具;`wait: true` 是它的默认,丢掉)。它不在了,
      宿主迁的时候把这里没有位置的几格丢掉、记进修订说明,而不是留下一个跑不起来的节点;
    - 这个入口**以前按路径哈希起的名字**:老版本 ComfyUI 存的图没有 id,在新版里打开再存一次就有了,工具名跟着从
      `wf_<路径哈希>`(表单入口 `wf_<路径哈希>_<表单 id>`)变成按 id 起的那个 —— 不迁的话,存着的节点从此找不到它。
      入参是同一张图推出来的,按同名接。
    """
    found: list[dict[str, Any]] = []
    if not entry.form_id:
        found.append({"tool": "run_workflow", "match": {"workflow": entry.id}, "rename": shape.rename,
                      "drop_if": {"wait": True}})
    by_path = f"wf_{_hash(entry.workflow.id)}" + (f"_{entry.form_id}" if entry.form_id else "")
    if name != by_path and name not in _FIXED_NAMES.values():
        found.append({"tool": by_path, "match": {}, "rename": {}, "drop_if": {}})
    return found


def _cache_path(comfy: Comfy) -> Path | None:
    """工具名 → 入口 id(模型 id;表单入口带 `#<表单 id>`)的对照表。**按服务器分开记**:持久目录是整个插件共用的,
    几台 ComfyUI 记在一个文件里就互相覆盖,每跑一次工具都得把那台服务器上的工作流整个重扫一遍。"""
    root = os.environ.get("MOSAEL_PLUGIN_DATA_DIR", "")
    return Path(root) / f"tools-{_hash(comfy.base)}.json" if root else None


def _remember(comfy: Comfy, names: dict[str, str]) -> None:
    path = _cache_path(comfy)
    if path is None:
        return
    try:
        path.write_text(json.dumps({tool: entry_id for entry_id, tool in names.items()}, ensure_ascii=False),
                        encoding="utf-8")
    except OSError:
        pass  # 记不下来只是下次要多扫一遍


def names_of(comfy: Comfy, workflow: models.Workflow, object_info: dict[str, Any]) -> dict[str, str]:
    """这张图每个入口的工具名(入口 id → 工具名):先看上次清单记下的对照表(那是和别的图一起排过撞名的),没记着的(刚加的
    表单)按这张图自己算。工作流库据此告诉宿主一张表单的工具叫什么(数「Mosael 里有几处在用它」)。"""
    known: dict[str, str] = {}
    path = _cache_path(comfy)
    if path is not None and path.is_file():
        try:
            known = {entry_id: tool for tool, entry_id in json.loads(path.read_text(encoding="utf-8")).items()}
        except (OSError, ValueError, AttributeError):
            known = {}
    return {entry_id: known.get(entry_id, tool) for entry_id, tool in tool_names(models.entries(workflow, object_info)).items()}


def runnable(workflow: models.Workflow, object_info: dict[str, Any]) -> bool:
    """这张图跑得起来吗:一个输出节点(保存、预览、显示文字……)都没有的,ComfyUI 不跑(`Prompt has no outputs`),
    原样跑一遍什么也交不回 —— 不做成工具(此前它的工具写着「交回它全部 0 个输出节点的产出」)。"""
    return bool(graph.output_nodes(workflow.api, object_info, workflow.titles))


def all_entries(comfy: Comfy, object_info: dict[str, Any], locale: str) -> list[models.Entry]:
    """这台服务器上每张图的每个入口(转不过来的图没有入口)。"""
    return [entry for workflow in models.each(comfy, object_info, locale) for entry in models.entries(workflow, object_info)]


def _listed(entry: models.Entry, names: dict[str, str], object_info: dict[str, Any]) -> bool:
    """这个入口报不报成工具:有名字、跑得起来,而且不是「上一版格式、带表单」那张图的完整入口(升级之前不报,见
    app_form.Marks.forms_await_upgrade —— 工作流里记着 `wf_<id>` 的老节点那时指的是表单)。"""
    return entry.id in names and runnable(entry.workflow, object_info) and not entry.workflow.marks.forms_await_upgrade


def catalog(comfy: Comfy, locale: str) -> dict[str, Any]:
    """`op: tools`:每张跑得起来的工作流(和内置文生图)的每个入口一个工具(`tools`),加上一次性的改名(`moved`,见
    models.MOVED_KEY:以前指着表单的工具名,改到表单入口的工具名)。名字照全部入口起(撞 id 要看每一张),报的是 `_listed` 的那些。"""
    object_info = comfy.object_info()
    entries = all_entries(comfy, object_info, locale)
    names = tool_names(entries)
    _remember(comfy, names)
    listed = [entry for entry in entries if _listed(entry, names, object_info)]
    return {
        "tools": [tool_for(entry, names[entry.id], object_info) for entry in listed],
        "moved": models.moved(listed, lambda entry: names[entry.id]),
    }


def _resolve(name: str, comfy: Comfy, object_info: dict[str, Any], locale: str) -> tuple[models.Loaded, models.Entry]:
    """工具名 → 那张图和它的那个入口。先看上次记下的对照表(按那张图的入口重算一遍工具名核对),对不上再整个扫一遍
    (工作流可能刚改过名)。"""
    path = _cache_path(comfy)
    known: dict[str, str] = {}
    if path is not None and path.is_file():
        try:
            known = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            known = {}
    entry_id = known.get(name)
    if entry_id:
        try:
            loaded, entry = models.pick(comfy, entry_id, object_info, locale)
            if tool_names(models.entries(entry.workflow, object_info)).get(entry_id) == name:
                return loaded, entry
        except ComfyError:
            pass
    entries = all_entries(comfy, object_info, locale)
    names = tool_names(entries)
    _remember(comfy, names)
    for entry in entries:
        if names.get(entry.id) == name:
            return models.pick(comfy, entry.id, object_info, locale)
    for entry in entries:
        # 一张表单的工具(完整工作流的工具名加 `_<表单 id>`),而那张图的表单还是上一版的格式:说清楚去升级,别说成「没有这张」
        if entry.workflow.marks.upgradable and not entry.form_id and name.startswith(f"{names.get(entry.id)}_"):
            raise models.outdated(entry.workflow.id, locale)
    raise ComfyError(say(locale, f"ComfyUI 里已经没有这张工作流了({name})—— 到插件页点「刷新模型」",
                         f"ComfyUI no longer has this workflow ({name}). Click Refresh models on the Plugins page."))


#: 一次最多解释几个工具名(宿主问的是画布上用不了的那几个插件节点)。
MAX_EXPLAIN = models.MAX_EXPLAIN


def explain(comfy: Comfy, asked: Any, locale: str) -> dict[str, Any]:
    """宿主记着、工具清单里没有的几个工具名现在为什么不在(工作流里用不了的插件节点,ADR 0045 修订之二):每个一条
    `{name, label, group, reason, upgrade}`,和模型的 `explain`(models.explain)同一套说法 —— 那张图的表单还是上一版格式、要升级
    (表单的工具,和带表单那张图的完整入口);工作流还在、这张表单没了;工作流不在了(改名、挪走、删了);入口在、只是跑不起来。
    名字不是这台 ComfyUI 起的(不以 `wf_` 开头)不回。只读,不写那台机器。"""
    if not isinstance(asked, list) or any(not isinstance(one, str) for one in asked):
        raise ComfyError(say(locale, "要解释的工具名形状不对", "The tool names to explain are malformed."))
    object_info = comfy.object_info()
    entries = all_entries(comfy, object_info, locale)
    names = tool_names(entries)
    by_name = {names[entry.id]: entry for entry in entries if entry.id in names}
    fulls = {names[entry.id]: entry for entry in entries if entry.id in names and not entry.form_id}
    out: list[dict[str, Any]] = []
    for name in dict.fromkeys(asked[:MAX_EXPLAIN]):
        if not name.startswith("wf_"):
            continue
        entry = by_name.get(name)
        if entry is not None and _listed(entry, names, object_info):
            continue
        base = next((full for prefix, full in fulls.items() if name == prefix or name.startswith(f"{prefix}_")), None)
        if base is None:
            out.append({"name": name, "label": _pair("这张工作流", "This workflow"), "group": None, "upgrade": False,
                        "reason": _pair("这台 ComfyUI 上已经没有这张工作流了 —— 可能改了名、挪了文件夹或删掉了。到工作流库里找到它,"
                                        "在节点上重新选一次",
                                        "This ComfyUI no longer has this workflow: it may have been renamed, moved to another "
                                        "folder or deleted. Find it in the workflow library and choose it on the node again.")})
            continue
        workflow = base.workflow
        form_id = name[len(names[base.id]) + 1:] if name != names[base.id] else ""
        label = workflow.label
        found = {"name": name, "label": _pair(f"{label} 的表单", f"Form of {label}") if form_id else _pair(label, label),
                 "group": {"id": workflow.id, "label": label, "entry": "form" if form_id else "full"}, "upgrade": False}
        if (form_id and workflow.marks.upgradable) or (not form_id and workflow.marks.forms_await_upgrade):
            found["reason"], found["upgrade"] = models.outdated(workflow.id, locale).said, True
        elif form_id and entry is None:
            found["reason"] = _pair(f"工作流「{label}」上已经没有这张表单了(删掉了)—— 换成它别的表单或完整工作流",
                                    f"The workflow “{label}” no longer has this form (it was deleted). Choose another of its "
                                    "forms or the full workflow.")
        else:
            found["reason"] = _pair(f"工作流「{label}」跑不起来:里面没有交出结果的节点",
                                    f"The workflow “{label}” can't run: it has no node that produces a result.")
        out.append(found)
    return {"tools": out}


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
    loaded, entry = _resolve(name, comfy, object_info, locale)
    api, defaults, titles = loaded.api, loaded.defaults, loaded.titles
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

    # 跑一张存好的工作流:种子没给就用它存着的;内置文生图的种子是占位符,照旧每次随机
    values = run.values_from(texts.get("prompt"), texts.get("negative"), parameters, defaults, keep_seed=not defaults)
    uploads: dict[str, list[str]] | None = None

    def build(seed: int | None) -> dict[str, Any]:
        """这一次要提交的图:填好入参(跑几遍时换上这一遍的种子),接上传好的素材。素材只传一次。"""
        nonlocal uploads
        filled = {**values, "seed": seed} if seed is not None else values
        prompt = graph.fill(api, filled, overrides, object_info, shape.prompts)
        if uploads is None:
            run.preflight(prompt, object_info, locale)
            uploads = run.upload(comfy, [{"role": f"slot:{node}", "path": path} for node, path in slots.items()]
                                 + ([{"role": "mask", "path": alpha_mask}] if alpha_mask else []))
        for role, names in uploads.items():
            if role == "mask":
                prompt = graph.wire_inputs(prompt, kind, {"mask": names}, shape.slots)
                continue
            node = role.removeprefix("slot:")
            if node in prompt:
                graph.put_input(prompt, node, names[0])
        return prompt

    from workflows import deliver  # 避免循环 import:workflows 也用这里的 output_key

    count = run.runs_from(parameters)
    if count > 1 and graph.counts_runs(api):
        # 跑 N 遍:循环提交 N 次,每次换一个种子(和生成那一路同一个 run.run_repeated)
        given = int(parameters["seed"]) if run._number(parameters.get("seed")) else None  # noqa: SLF001
        repeated = run.run_repeated(comfy, build, count, given, emit, locale, titles)
        if not repeated.runs:
            raise ComfyError(repeated.failures[0][1])
        result = deliver(comfy, [(prompt_id, finished) for prompt_id, finished, _ in repeated.runs], build(None),
                         titles, locale, entry.workflow.id, include_previews=include_previews, workflow=entry.workflow.id,
                         one_workflow=True)
        result["seeds"] = [seed for _, _, seed in repeated.runs]
        note = run.repeat_note(repeated, locale)
        if note:
            result["note"] = note
            result["summary"] = f"{result['summary']}({note})"
        return result
    prompt = build(None)
    prompt_id, finished = run.run_prompt(comfy, prompt, emit, locale, titles)
    return deliver(comfy, [(prompt_id, finished or {})], prompt, titles, locale, entry.workflow.id,
                   include_previews=include_previews, workflow=entry.workflow.id)
