"""模型库(ADR 0034):这台 ComfyUI 上有哪些模型文件 —— 列出、读元数据、推断底模家族、找哪几张工作流在用、缺哪些。

宿主按 `op` 问(见 main._generation):

    {"op": "library"}                         → 全部模型文件 + 各目录数目 + 工作流缺的模型 + 下载走哪条路
    {"op": "detail", "folder", "name"}        → 一个文件的完整元数据(文件头里的标量)与训练标签

用到的 ComfyUI 接口(0.38.0 实测,见 ADR 0034 的表):

- `/experiment/models`:每个模型目录在磁盘上的位置;`/experiment/models/{目录}`:文件名、目录序号、大小、改动时间;
- `/experiment/models/preview/{目录}/{序号}/{名字}`:预览图(没有就 404)—— 地址交给宿主,宿主去取、去缓存;
- `/view_metadata/{目录}?filename=`:safetensors 文件头里的 `__metadata__`。一次约 40ms,几百个文件第一次要读一阵:
  读到的摘要按「服务器 + 目录 + 名字 + 大小 + 改动时间」记在持久目录里,第二次只读目录。

老版本没有 `/experiment/models` 时退回 `/models/{目录}`:只有名字,没有大小和预览。
"""

from __future__ import annotations

import json
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib import parse

import install
import models
from families import family_of
from comfy_http import Comfy
from sources import canonical_url
from lines import ComfyError, say
from model_files import SKIPPED_FOLDERS, data_file, files_in, folder_info, load_json, metadata_of, save_json
from model_files import norm as _norm
#: 同时读几个文件头。ComfyUI 是别人的机器、可能正在出图:几个并发就够,别把它的事件循环堵满。
METADATA_WORKERS = 4
#: 列表里一个文件最多带几个触发词(全部的在详情里)。
LIST_TRIGGERS = 5
#: 一次回答的上限是 1 MB(宿主的规矩);留点余量。几千个文件时先削触发词和「在用的工作流」。
OUTPUT_BUDGET = 900_000
#: 详情里训练标签最多列几个。
DETAIL_TAGS = 100

def _tag_counts(meta: dict[str, Any]) -> Counter[str]:
    """`ss_tag_frequency`(一段 JSON:数据集 → 标签 → 次数)按标签合起来。"""
    raw = meta.get("ss_tag_frequency")
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return Counter()
    counts: Counter[str] = Counter()
    for tags in (parsed or {}).values() if isinstance(parsed, dict) else []:
        if isinstance(tags, dict):
            for tag, count in tags.items():
                if isinstance(count, (int, float)) and str(tag).strip():
                    counts[str(tag).strip()] += int(count)
    return counts


def triggers_of(meta: dict[str, Any]) -> tuple[list[str], str]:
    """触发词:作者写在文件头里的(`modelspec.trigger_phrase` / `ss_trigger_words`)→ `metadata`;都没有时取训练标签里
    出现最多的几个 → `tags`(常见词,不一定是作者指定的触发词,界面上标明)。"""
    for key in ("modelspec.trigger_phrase", "ss_trigger_words"):
        raw = meta.get(key)
        if isinstance(raw, str) and raw.strip():
            return [one.strip() for one in raw.split(",") if one.strip()][:30], "metadata"
    counts = _tag_counts(meta)
    if counts:
        return [tag for tag, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:LIST_TRIGGERS]], "tags"
    return [], ""


def _title_of(meta: dict[str, Any]) -> str:
    for key in ("modelspec.title", "ss_output_name"):
        raw = meta.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()[:200]
    return ""


def summarize(folder: str, name: str, meta: dict[str, Any]) -> dict[str, Any]:
    """一个文件的元数据 → 列表里那几格(记进缓存的就是它)。"""
    family, family_source = family_of(folder, name, meta)
    triggers, triggers_source = triggers_of(meta)
    return {"family": family, "family_source": family_source, "triggers": triggers[:LIST_TRIGGERS],
            "triggers_source": triggers_source, "title": _title_of(meta)}


# --- 持久目录里的记录 ---------------------------------------------------------

def _cache_key(folder: str, item: dict[str, Any]) -> str:
    return f"{folder}\n{item.get('name')}\n{item.get('size')}\n{item.get('modified')}"


# --- 工作流:在用哪些文件、声明了哪些下载地址 ---------------------------------

#: 一键下载只认这几个站(和 ComfyUI 官方前端缺模型时的白名单同一份):工作流文件来自四面八方,不替陌生链接背书。
TRUSTED_SOURCES = ("https://huggingface.co/", "https://civitai.com/")


def _strings(value: Any) -> set[str]:
    out: set[str] = set()
    if isinstance(value, str):
        if value.strip():
            out.add(_norm(value))
    elif isinstance(value, list):
        for one in value:
            out |= _strings(one)
    elif isinstance(value, dict):
        for one in value.values():
            out |= _strings(one)
    return out


def _nodes(ui_graph: dict[str, Any]) -> list[dict[str, Any]]:
    """一张图里的全部节点(含子图里的)。API 格式的图没有 `nodes`,按 {id: {class_type, inputs}} 收。"""
    if isinstance(ui_graph.get("nodes"), list):
        found = [one for one in ui_graph["nodes"] if isinstance(one, dict)]
        for sub in (ui_graph.get("definitions") or {}).get("subgraphs") or []:
            if isinstance(sub, dict):
                found += [one for one in sub.get("nodes") or [] if isinstance(one, dict)]
        return found
    return [one for one in ui_graph.values() if isinstance(one, dict) and "class_type" in one]


def scan_workflow(ui_graph: dict[str, Any]) -> tuple[list[str], list[dict[str, str]]]:
    """一张图:(节点输入里写着的全部字符串, 真在用的那些下载声明)。

    下载声明是节点的 `properties.models`(官方模板的写法)和顶层的 `models`。只收**节点当前真在用**的:节点改选了别的
    文件,声明就过期了;顶层的声明要在某个节点的输入里写着。"""
    nodes = _nodes(ui_graph)
    used: set[str] = set()
    declared: list[dict[str, str]] = []
    for node in nodes:
        values = _strings(node.get("widgets_values")) | _strings(node.get("inputs") if "class_type" in node else None)
        used |= values
        for spec in (node.get("properties") or {}).get("models") or [] if isinstance(node.get("properties"), dict) else []:
            if isinstance(spec, dict) and _norm(str(spec.get("name") or "")) in values:
                declared.append(spec)
    for spec in ui_graph.get("models") or [] if isinstance(ui_graph.get("models"), list) else []:
        if isinstance(spec, dict) and _norm(str(spec.get("name") or "")) in used:
            declared.append(spec)
    clean = [
        {"name": _norm(str(spec.get("name") or "")), "folder": str(spec.get("directory") or "").strip(),
         "url": canonical_url(str(spec.get("url") or "").strip())}
        for spec in declared
    ]
    return sorted(used), [one for one in clean if one["name"] and one["folder"]]


def _workflows(comfy: Comfy) -> list[tuple[str, str, list[str], list[dict[str, str]]]]:
    """每张保存的工作流:(id, 名字, 在用的字符串, 下载声明)。按「路径 + 大小 + 改动时间」记在持久目录里。"""
    cache_path = data_file(comfy, "workflow-models")
    cache = load_json(cache_path)
    fresh: dict[str, Any] = {}
    out: list[tuple[str, str, list[str], list[dict[str, str]]]] = []
    listing = {str(item.get("path")): item for item in comfy.workflow_listing()}
    workflows, _others = comfy.saved_files()
    for path in workflows:
        item = listing.get(path) or {}
        key = f"{path}\n{item.get('size')}\n{item.get('modified')}"
        entry = cache.get(key)
        if not isinstance(entry, dict):
            try:
                used, declared = scan_workflow(comfy.fetch_workflow(path))
            except ComfyError:
                continue
            entry = {"used": used, "declared": declared}
        fresh[key] = entry
        out.append((path, models.label_of(path), list(entry.get("used") or []), list(entry.get("declared") or [])))
    if fresh != cache:
        save_json(cache_path, fresh)
    return out


# --- op: library ------------------------------------------------------------

def library(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    info = folder_info(comfy)
    listing: dict[str, list[dict[str, Any]]] = {}
    if info is None:
        # 老版本:只有名字
        for folder in comfy.model_folders() or []:
            if folder not in SKIPPED_FOLDERS:
                listing[folder] = [{"name": name} for name in comfy.models_in(folder)]
    else:
        for folder in info:
            if folder not in SKIPPED_FOLDERS:
                listing[folder] = files_in(comfy, folder)

    cache_path = data_file(comfy, "library")
    cache = load_json(cache_path)
    fresh: dict[str, Any] = {}
    wanted = [(folder, item) for folder, items in listing.items() for item in items
              if str(item.get("name")).lower().endswith(".safetensors") and _cache_key(folder, item) not in cache]

    def read(job: tuple[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
        folder, item = job
        return _cache_key(folder, item), summarize(folder, item["name"], metadata_of(comfy, folder, item["name"]) or {})

    if wanted:
        with ThreadPoolExecutor(max_workers=METADATA_WORKERS) as pool:
            fresh.update(dict(pool.map(read, wanted)))

    workflows = _workflows(comfy)
    used_by: dict[str, list[dict[str, str]]] = {}
    for ident, label, used, _declared in workflows:
        for value in used:
            used_by.setdefault(value, []).append({"id": ident, "label": label})

    out_models: list[dict[str, Any]] = []
    for folder, items in listing.items():
        for item in items:
            name = str(item["name"])
            key = _cache_key(folder, item)
            summary = fresh.get(key) or cache.get(key)
            if summary is None:
                summary = summarize(folder, name, {})  # 不是 safetensors:只按文件名猜
            else:
                fresh[key] = summary
            entry: dict[str, Any] = {"folder": folder, "name": name}
            for field in ("size", "modified"):
                if isinstance(item.get(field), (int, float)):
                    entry[field] = item[field]
            entry.update({key: value for key, value in summary.items() if value})
            users = used_by.get(_norm(name))
            if users:
                entry["used_by"] = users
            if info is not None:
                entry["preview"] = f"{parse.quote(folder, safe='')}/{int(item.get('pathIndex') or 0)}/" \
                                   f"{parse.quote(name, safe='/')}"
            out_models.append(entry)
    if fresh != cache:
        save_json(cache_path, fresh)

    present = {(folder, _norm(str(item["name"]))) for folder, items in listing.items() for item in items}
    missing: dict[tuple[str, str], dict[str, Any]] = {}
    for ident, label, _used, declared in workflows:
        for spec in declared:
            if (spec["folder"], spec["name"]) in present or not spec["url"].startswith(TRUSTED_SOURCES):
                continue
            found = missing.setdefault((spec["folder"], spec["name"]),
                                       {"folder": spec["folder"], "name": spec["name"], "url": spec["url"], "workflows": []})
            if all(one["id"] != ident for one in found["workflows"]):
                found["workflows"].append({"id": ident, "label": label})

    out: dict[str, Any] = {
        "folders": [{"name": folder, "count": len(items)} for folder, items in listing.items()],
        "models": out_models,
        "missing": list(missing.values()),
        "download": install.describe(comfy, info, listing, locale),
    }
    if info is not None:
        out["preview_base"] = f"{comfy.base}/experiment/models/preview/"
        if comfy.headers:
            out["preview_headers"] = dict(comfy.headers)
    return _within_budget(out, locale)


def _within_budget(out: dict[str, Any], locale: str) -> dict[str, Any]:
    """一次回答最多 1 MB。几千个文件时先削触发词、「在用的工作流」、标题,还不够就只列前面的,并说一句。"""
    def size() -> int:
        return len(json.dumps(out, ensure_ascii=False).encode("utf-8"))

    for trim in ("triggers", "used_by", "title"):
        if size() <= OUTPUT_BUDGET:
            return out
        for entry in out["models"]:
            entry.pop(trim, None)
            if trim == "triggers":
                entry.pop("triggers_source", None)
    while size() > OUTPUT_BUDGET and out["models"]:
        out["models"] = out["models"][: int(len(out["models"]) * 0.8)]
    note = say(locale, f"文件太多,只列出了前 {len(out['models'])} 个", f"Too many files; only the first {len(out['models'])} are listed")
    out["download"] = {**out["download"], "note": f"{out['download'].get('note', '')} {note}".strip()}
    return out


# --- op: detail -------------------------------------------------------------

def detail(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    folder, name = str(payload.get("folder") or ""), str(payload.get("name") or "")
    meta = metadata_of(comfy, folder, name)
    if meta is None:
        why = say(locale, "这个文件没有可读的元数据:只有 safetensors 文件的文件头里有,而且作者不一定写了",
                  "This file has no readable metadata: only safetensors files carry it in their header, and not every author writes it")
        return {"folder": folder, "name": name, "metadata": {}, "tags": [], "note": why}
    counts = _tag_counts(meta)
    shown = {
        key: value for key, value in meta.items()
        if key != "ss_tag_frequency" and not (isinstance(value, str) and value.startswith("data:"))
    }
    tags = [{"tag": tag, "count": count}
            for tag, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:DETAIL_TAGS]]
    return {"folder": folder, "name": name, "metadata": shown, "tags": tags, **summarize(folder, name, meta)}
