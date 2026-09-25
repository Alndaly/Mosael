"""给智能体和工作流用的三个工具:看有哪些工作流、跑一张工作流、把 ComfyUI 里的产出收进素材库。

和「替宿主做生成」(run.generate)的区别:生成是**一段提示词 → 一份成片**,由宿主的生成任务管着
(回执、用量、重启后接着等);这里是**一张工作流原样跑一遍**,输入可以是图、蒙版、视频、音频、任意节点
上的值,交回**全部**产出(每个保存 / 预览节点的每一个文件,以及显示文字的节点说的话)—— 放大、抠图、
局部重绘、修脸、补帧,用的都是用户自己的那张图。

长活怎么办(见 docs/PLUGIN_MANIFEST 的「预算」与 comfyui 指南):工具一次最多跑 30 分钟,智能体那一侧
一次只等 3 分钟。所以 `run_workflow` 可以 `wait: false` 只提交、马上交回任务号,之后用 `import_outputs`
按任务号取回;要跑一小时的视频走生成(每张工作流本来就是一个生成模型),那里有回执和重启续等。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import graph
import models
import run
import tooling
from comfy_http import Comfy
from lines import ComfyError, say

#: 一次最多交回多少份文件(和宿主收产出的上限对齐,见 domain/plugins/artifacts.MAX_ARTIFACTS)。
MAX_FILES = 64
#: `import_outputs` 最多往回翻几条历史。
MAX_HISTORY = 20
#: `import_outputs` 最多等多久(秒)。智能体一次工具调用只等 180 秒,留出收文件的时间。
MAX_WAIT_SECONDS = 150
#: 给智能体看的参数可选值最多列几个(checkpoint 下拉动辄几十个,全列出来工具结果就爆了)。
_ENUM_PREVIEW = 12


def _text(value: Any, locale: str) -> str:
    if isinstance(value, dict):
        return str(value.get("zh" if locale.startswith("zh") else "en") or next(iter(value.values()), ""))
    return str(value or "")


# ---------------------------------------------------------------------------
# list_workflows
# ---------------------------------------------------------------------------


def list_workflows(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """保存的每张工作流(加内置文生图、粘贴的模板):能喂什么、能调什么、会交出什么。"""
    query = str(payload.get("query") or "").strip().lower()
    object_info = comfy.object_info()
    found: list[dict[str, Any]] = []
    entries = list(models.each(comfy, object_info, locale))
    names = tooling.tool_names(entries)
    for entry in entries:
        name = _text(entry.label, locale)
        if query and query not in entry.id.lower() and query not in name.lower():
            continue
        if entry.problem:
            found.append({"id": entry.id, "label": name, "error": entry.problem})
            continue
        described = inspect(entry.id, name, entry.api, object_info, entry.titles, locale)
        if entry.id in names:
            # 这张工作流自己的那个工具(输入就是它自己的节点):智能体优先调它,而不是 run_workflow
            described["tool"] = names[entry.id]
        found.append(described)
    return {
        "workflows": found,
        "count": len(found),
        "summary": say(locale, f"{len(found)} 张工作流", f"{len(found)} workflows"),
    }


def inspect(model_id: str, label: str, api: dict[str, Any], object_info: dict[str, Any],
            titles: dict[str, str], locale: str) -> dict[str, Any]:
    kind = graph.kind_of(api)
    found_slots = graph.slots(api, kind, titles)
    roles = graph.text_roles(api)
    size_node = graph.size_node(api)
    size = ""
    if size_node is not None:
        inputs = api[size_node]["inputs"]
        size = f"{inputs.get('width')}x{inputs.get('height')}"
    parameters = []
    for key, spec in graph.tunable(api, object_info, titles).items():
        entry: dict[str, Any] = {"key": key, "title": _text(spec.get("title"), locale), "type": spec["type"]}
        if "default" in spec:
            entry["default"] = spec["default"]
        if isinstance(spec.get("enum"), list):
            entry["options"] = spec["enum"][:_ENUM_PREVIEW]
            if len(spec["enum"]) > _ENUM_PREVIEW:
                entry["options_total"] = len(spec["enum"])
        for bound in ("minimum", "maximum"):
            if bound in spec:
                entry[bound] = spec[bound]
        parameters.append(entry)
    image_slots = [slot for slot in found_slots if slot["media"] == "image"]
    return {
        "id": model_id,
        "label": label,
        "kind": kind,
        "features": graph.features(api, found_slots),
        "prompt": "prompt" in roles.values(),
        "negative_prompt": "negative" in roles.values(),
        "size": size,
        # 智能体按这个顺序给 `image` / `images`:第一个读图的节点吃 `image`,后面的依次吃 `images`
        "inputs": [
            {"node": slot["node"], "title": slot["title"], "class_type": slot["class_type"],
             "media": slot["media"], "role": slot["role"],
             "argument": _argument_for(slot, image_slots)}
            for slot in found_slots
        ],
        "parameters": parameters,
        "outputs": graph.output_nodes(api, object_info, titles),
    }


def _argument_for(slot: dict[str, str], image_slots: list[dict[str, str]]) -> str:
    """这个槽位由 `run_workflow` 的哪个参数喂。"""
    if slot["media"] == "image":
        index = image_slots.index(slot)
        return "image" if index == 0 else f"images[{index - 1}]"
    return {"mask": "mask", "video": "video", "audio": "audio"}.get(slot["media"], "")


# ---------------------------------------------------------------------------
# run_workflow
# ---------------------------------------------------------------------------


def _paths(value: Any) -> list[str]:
    if isinstance(value, str) and value.strip():
        return [value]
    if isinstance(value, list):
        return [str(one) for one in value if isinstance(one, str) and one.strip()]
    return []


def _assign(found_slots: list[dict[str, str]], payload: dict[str, Any], locale: str) -> list[dict[str, str]]:
    """`image` / `images` / `mask` / `video` / `audio` → 按槽位顺序排好的 `{role, path}`(交给 run.upload)。"""
    wanted = {
        "image": _paths(payload.get("image")) + _paths(payload.get("images")),
        "mask": _paths(payload.get("mask")),
        "video": _paths(payload.get("video")),
        "audio": _paths(payload.get("audio")),
    }
    assigned: list[dict[str, str]] = []
    for media, paths in wanted.items():
        if not paths:
            continue
        targets = [slot for slot in found_slots if slot["media"] == media]
        if media == "mask" and not targets:
            # 没有单独的蒙版节点也能收:LoadImage 的 alpha 那一路会被改接到给的蒙版上(见 graph.wire_inputs)
            if any(slot["class_type"] == "LoadImage" for slot in found_slots):
                assigned.append({"role": "mask", "path": paths[0]})
                continue
        if not targets:
            raise ComfyError(say(
                locale,
                f"这张工作流里没有读{_media_zh(media)}的节点,给的{_media_zh(media)}接不上去",
                f"This workflow has no node that loads {_media_en(media)}, so the given {_media_en(media)} has nowhere to go",
            ))
        if len(paths) > len(targets):
            raise ComfyError(say(
                locale,
                f"给了 {len(paths)} 份{_media_zh(media)},这张工作流只有 {len(targets)} 个读{_media_zh(media)}的节点",
                f"Got {len(paths)} {_media_en(media)} inputs but the workflow only has {len(targets)} {_media_en(media)} loader(s)",
            ))
        for slot, path in zip(targets, paths):
            assigned.append({"role": slot["role"], "path": path})
    return assigned


def _media_zh(media: str) -> str:
    return {"image": "图", "mask": "蒙版", "video": "视频", "audio": "音频"}.get(media, media)


def _media_en(media: str) -> str:
    return {"image": "images", "mask": "masks", "video": "videos", "audio": "audio"}.get(media, media)


def run_workflow(payload: dict[str, Any], comfy: Comfy, locale: str, emit: run.Emit) -> dict[str, Any]:
    model_id = str(payload.get("workflow") or "").strip()
    if not model_id:
        raise ComfyError(say(locale, "要跑哪张工作流?`workflow` 填 list_workflows 里的 id",
                             "Which workflow? Set `workflow` to an id from list_workflows"))
    object_info = comfy.object_info()
    api, defaults, titles = models.load(comfy, model_id, object_info, locale)
    kind = graph.kind_of(api)
    parameters = {key: payload[key] for key in ("seed", "width", "height", "steps") if key in payload}
    if "num_images" in payload:
        parameters["num_images"] = payload["num_images"]
    prompt_text = payload.get("prompt")
    values = run.values_from(prompt_text, payload.get("negative_prompt"), parameters, defaults)
    if prompt_text is None:
        values.pop("prompt", None)  # 没给提示词就用工作流里写好的那一句
    if payload.get("negative_prompt") is None and not defaults:
        values.pop("negative", None)
    if "seed" not in payload and not defaults:
        values.pop("seed", None)  # 跑一张存好的工作流:种子没给就用它存着的,可复现
    prompt = graph.fill(api, values, {})
    unknown = []
    for key, value in (payload.get("values") or {}).items():
        if not graph.set_value(prompt, str(key), value, titles):
            unknown.append(str(key))
    if unknown:
        raise ComfyError(say(locale, f"这些值在工作流里对不上(写成「节点 id 或节点标题.输入名」):{', '.join(unknown)}",
                             f"These values match no literal input (use “node id or title.input name”): {', '.join(unknown)}"))
    found_slots = graph.slots(prompt, kind, titles)
    uploaded = run.upload(comfy, _assign(found_slots, payload, locale))
    if uploaded:
        prompt = graph.wire_inputs(prompt, kind, uploaded)
    wait = payload.get("wait") is not False
    prompt_id, entry = run.run_prompt(comfy, prompt, emit, locale, titles, wait=wait)
    if entry is None:
        return {
            "workflow": model_id,
            "prompt_id": prompt_id,
            "status": "queued",
            "summary": say(locale, f"已提交到 ComfyUI(任务 {prompt_id});跑完后用 import_outputs 取回产出",
                           f"Submitted to ComfyUI (task {prompt_id}); fetch the outputs with import_outputs when it is done"),
        }
    return deliver(comfy, [(prompt_id, entry)], prompt, titles, locale, model_id,
                    include_previews=payload.get("include_previews") is True, workflow=model_id)


# ---------------------------------------------------------------------------
# import_outputs
# ---------------------------------------------------------------------------


def import_outputs(payload: dict[str, Any], comfy: Comfy, locale: str, emit: run.Emit) -> dict[str, Any]:
    """把 ComfyUI 历史里的产出收进素材库:按任务号取一个,或者取最近的几个。"""
    prompt_id = str(payload.get("prompt_id") or "").strip()
    include_previews = payload.get("include_previews") is True
    if prompt_id:
        entry = run.history_entry(comfy, prompt_id)
        if entry is None:
            running, pending = comfy.queue()
            if prompt_id not in running and prompt_id not in pending:
                raise ComfyError(say(locale, f"ComfyUI 里找不到任务 {prompt_id}", f"ComfyUI has no task {prompt_id}"))
            wait = min(MAX_WAIT_SECONDS, max(0, int(payload.get("wait_seconds") or 0)))
            if wait:
                entry = run.follow_poll(comfy, prompt_id, emit, locale, deadline=time.monotonic() + wait)
            if entry is None:
                state = "running" if prompt_id in running else "queued"
                return {
                    "prompt_id": prompt_id,
                    "status": state,
                    "summary": say(locale, f"任务 {prompt_id} 还没跑完({'在跑' if state == 'running' else '排队中'})",
                                   f"Task {prompt_id} is not finished yet ({state})"),
                }
        return deliver(comfy, [(prompt_id, entry)], None, {}, locale, prompt_id, include_previews=include_previews)
    last = min(MAX_HISTORY, max(1, int(payload.get("last") or 1)))
    history = comfy.history(max_items=last)
    entries = [(key, value) for key, value in history.items() if isinstance(value, dict)][-last:]
    if not entries:
        raise ComfyError(say(locale, "ComfyUI 的历史是空的", "ComfyUI's history is empty"))
    return deliver(comfy, entries, None, {}, locale, "comfyui-history", include_previews=include_previews)


# ---------------------------------------------------------------------------
# 交回产出
# ---------------------------------------------------------------------------


def deliver(comfy: Comfy, entries: list[tuple[str, dict[str, Any]]], prompt: dict[str, Any] | None,
             titles: dict[str, str], locale: str, stem: str, *, include_previews: bool,
             workflow: str = "") -> dict[str, Any]:
    """一条或几条历史 → 取回**全部**文件交给宿主(`artifacts`),外加一份按节点分的摘要和所有文字产出。"""
    files: list[dict[str, Any]] = []
    texts: list[dict[str, Any]] = []
    for prompt_id, entry in entries:
        found, said = graph.all_outputs(entry, include_previews=include_previews, prompt=prompt)
        for one in found:
            one["prompt_id"] = prompt_id
        for one in said:
            one["prompt_id"] = prompt_id
        files.extend(found)
        texts.extend(said)
    truncated = max(0, len(files) - MAX_FILES)
    files = files[:MAX_FILES]
    if not files and not texts:
        raise ComfyError(say(
            locale,
            "ComfyUI 跑完了,但没有产出 —— 工作流里需要一个保存 / 预览节点(SaveImage、PreviewImage、视频合成…)",
            "ComfyUI finished but produced nothing. The workflow needs a save / preview node (SaveImage, PreviewImage, a video combine…)",
        ))
    artifacts = run.download(comfy, files, Path(stem).stem or "comfyui") if files else []
    # 每个输出节点的第一份记成一个具名输出(`image_9` / `video_30` …):声明了按节点输出的工具(每张工作流
    # 自己的那个)下游可以直接接「那个保存节点的图」。宿主按 artifact 上的 `output` 把素材 id 填进去。
    named: set[str] = set()
    for one, artifact in zip(files, artifacts):
        key = tooling.output_key(one["media"], one["node"])
        if key not in named and len(entries) == 1:
            artifact["output"] = key
            named.add(key)
    summary: dict[str, dict[str, Any]] = {}
    for one, artifact in zip(files, artifacts):
        node = summary.setdefault(f"{one['prompt_id']}:{one['node']}", _node_summary(one, titles))
        node["files"].append(artifact["filename"])
        node["media"] = one["media"] if node["media"] in ("", one["media"]) else "mixed"
    for one in texts:
        node = summary.setdefault(f"{one['prompt_id']}:{one['node']}", _node_summary(one, titles))
        node["texts"].append(one["text"])
    counts: dict[str, int] = {}
    for one in files:
        counts[one["media"]] = counts.get(one["media"], 0) + 1
    node_texts: dict[str, list[str]] = {}
    for one in texts:
        node_texts.setdefault(tooling.output_key("text", one["node"]), []).append(one["text"])
    result: dict[str, Any] = {
        **({key: "\n".join(values) for key, values in node_texts.items()} if len(entries) == 1 else {}),
        "prompt_id": entries[0][0] if len(entries) == 1 else "",
        "prompt_ids": [prompt_id for prompt_id, _ in entries],
        "status": "succeeded",
        "artifacts": artifacts,
        "outputs": list(summary.values()),
        "texts": [one["text"] for one in texts],
        "counts": counts,
        "summary": _summary(counts, len(texts), truncated, locale),
    }
    if workflow:
        result["workflow"] = workflow
    return result


def _node_summary(one: dict[str, Any], titles: dict[str, str]) -> dict[str, Any]:
    return {"prompt_id": one["prompt_id"], "node": one["node"], "class_type": one["class_type"],
            "title": titles.get(one["node"]) or one["class_type"], "media": "", "files": [], "texts": []}


def _summary(counts: dict[str, int], texts: int, truncated: int, locale: str) -> str:
    names_zh = {"image": "张图", "video": "段视频", "audio": "段音频"}
    names_en = {"image": "image(s)", "video": "video(s)", "audio": "audio file(s)"}
    zh = [f"{n} {names_zh.get(media, '份文件')}" for media, n in counts.items()]
    en = [f"{n} {names_en.get(media, 'file(s)')}" for media, n in counts.items()]
    if texts:
        zh.append(f"{texts} 段文字")
        en.append(f"{texts} text output(s)")
    said = say(locale, "、".join(zh), ", ".join(en))
    if truncated:
        said += say(locale, f"(另有 {truncated} 份超出上限没有取回)", f" ({truncated} more over the limit were skipped)")
    return said
