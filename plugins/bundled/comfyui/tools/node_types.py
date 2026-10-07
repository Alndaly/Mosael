"""节点类型(ADR 0042 §3 `node_types`):在这台 ComfyUI 的节点定义里找,回它的输入(类型、必填、可选值、缺省值)和输出。

    {"op": "node_types", "classes": ["KSampler", …]}       → 这几类(一类一类问,便宜)
    {"op": "node_types", "query": "lora loader", "limit"?}  → 按名字、显示名、类别、说明、来自哪个包找(要全部节点的定义 ——
                                                              node_catalog.catalog,记着,`/object_info` 变了才重取)

下拉的可选值只列前面一些(一个 LoRA 目录几百个文件),写明一共多少个。
"""

from __future__ import annotations

import re
from typing import Any

import node_catalog
from comfy_http import Comfy
from lines import ComfyError, say
from workflow_import import _type_of
from workflow_library import _choices

#: 一次最多回多少类。
MAX_RESULTS = 30
#: 一格下拉最多列多少个可选值。
MAX_OPTIONS = 30
#: 说明最多多少字。
MAX_DESCRIPTION = 400


def _pack(spec: dict[str, Any]) -> str:
    """来自哪儿:`custom_nodes.<包的目录>` → 那个包;核心节点(nodes、comfy_extras.*、comfy_api_nodes.*)是 core。"""
    module = str(spec.get("python_module") or "")
    if module.startswith("custom_nodes."):
        return module.split(".", 2)[1]
    return "core" if module else ""


def describe(name: str, spec: dict[str, Any]) -> dict[str, Any]:
    """一类节点给智能体看的那一份。"""
    declared = spec.get("input") if isinstance(spec.get("input"), dict) else {}
    inputs: list[dict[str, Any]] = []
    for section in ("required", "optional"):
        defs = declared.get(section) if isinstance(declared.get(section), dict) else {}
        for input_name, definition in defs.items():
            options = definition[1] if isinstance(definition, list) and len(definition) > 1 and isinstance(definition[1], dict) else {}
            entry: dict[str, Any] = {"name": input_name, "type": _type_of(definition), "required": section == "required"}
            choices = _choices(definition)
            if choices is not None:
                entry["options"] = [str(one) for one in choices[:MAX_OPTIONS]]
                if len(choices) > MAX_OPTIONS:
                    entry["options_count"] = len(choices)
            for key in ("default", "min", "max", "step"):
                value = options.get(key)
                if isinstance(value, (str, int, float, bool)):
                    entry[key] = value[:200] if isinstance(value, str) else value
            if options.get("forceInput"):
                entry["socket"] = True
            if options.get("multiline"):
                entry["multiline"] = True
            inputs.append(entry)
    outputs_raw = spec.get("output") if isinstance(spec.get("output"), list) else []
    names = spec.get("output_name") if isinstance(spec.get("output_name"), list) else []
    outputs = [{"name": str(names[index]) if index < len(names) else str(kind), "type": "COMBO" if isinstance(kind, list) else str(kind)}
               for index, kind in enumerate(outputs_raw)]
    out: dict[str, Any] = {
        "type": name,
        "display_name": str(spec.get("display_name") or name)[:200],
        "category": str(spec.get("category") or "")[:200],
        "pack": _pack(spec),
        "inputs": inputs,
        "outputs": outputs,
    }
    description = str(spec.get("description") or "").strip()
    if description:
        out["description"] = description[:MAX_DESCRIPTION]
    if spec.get("output_node"):
        out["output_node"] = True
    if spec.get("deprecated"):
        out["deprecated"] = True
    return out


def _score(name: str, spec: dict[str, Any], terms: list[str], phrase: str) -> int:
    fields = {
        "name": name.lower(),
        "display": str(spec.get("display_name") or "").lower(),
        "category": str(spec.get("category") or "").lower(),
        "description": str(spec.get("description") or "").lower(),
        "pack": _pack(spec).lower(),
    }
    compact = phrase.replace(" ", "")
    if phrase == fields["name"] or compact == fields["name"]:
        return 1000
    score = 0
    for term in terms:
        hits = [key for key, text in fields.items() if term in text]
        if not hits:
            return 0
        score += 30 if "name" in hits else 20 if "display" in hits else 10 if "category" in hits or "pack" in hits else 3
    if phrase and (phrase in fields["name"] or phrase in fields["display"] or compact in fields["name"]):
        score += 40
    if spec.get("deprecated"):
        score -= 25
    return score


def node_types(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    limit = payload.get("limit")
    limit = max(1, min(MAX_RESULTS, int(limit))) if isinstance(limit, int) and not isinstance(limit, bool) else 10
    classes = payload.get("classes")
    if classes is not None:
        if not isinstance(classes, list) or not all(isinstance(one, str) for one in classes) or len(classes) > MAX_RESULTS:
            raise ComfyError(say(locale, f"要查的节点类型得是一串名字(最多 {MAX_RESULTS} 个)",
                                 f"The node types to look up must be a list of names (at most {MAX_RESULTS})"))
        found = node_catalog.classes(comfy, classes)
        return {"types": [describe(name, found[name]) for name in classes if name in found],
                "unknown": [name for name in classes if name not in found]}
    query = str(payload.get("query") or "").strip().lower()
    if not query:
        raise ComfyError(say(locale, "给一个关键词(名字、类别、用途)或者几个节点类型名", "Give a keyword (name, category, purpose) or some node type names"))
    terms = [one for one in re.split(r"[\s,,/]+", query) if one]
    catalog = node_catalog.catalog(comfy)
    ranked = sorted(((score, name) for name, spec in catalog.items() if (score := _score(name, spec, terms, query)) > 0),
                    key=lambda one: (-one[0], one[1]))
    return {"types": [describe(name, catalog[name]) for _, name in ranked[:limit]], "matched": len(ranked),
            "total": len(catalog)}


__all__ = ["describe", "node_types"]
