"""工作流库(ADR 0035):这台 ComfyUI 上存着的工作流 —— 列出、取原文、复制、改名、挪进 / 挪出回收目录。

宿主按 `op` 问(见 main._generation):

    {"op": "workflows"}                                → 全部工作流(图摘要、识别出的输入 / 参数 / 输出、用到的模型、缺什么)
                                                          + 不是工作流的文件 + 回收目录里的 + Manager 的版本
    {"op": "workflow", "path"}                         → 一张的原文
    {"op": "copy_workflow", "path", "new_path"}        → 复制(副本换一个新的图 id)
    {"op": "rename_workflow", "path", "new_path"}      → 改名 / 挪目录
    {"op": "trash_workflow", "path"}                   → 「删除」:挪进回收目录
    {"op": "restore_workflow", "path", "new_path"}     → 从回收目录挪回去

用到的 ComfyUI 接口(0.38.0,写 / 移动照源码 app/user_manager.py 核对,见 ADR 0035 的表):

- `GET /api/userdata?dir=…&recurse=true&full_info=true` 列目录;`GET /api/userdata/{file}` 取一份;
- `POST /api/userdata/{file}?overwrite=false` 写一份(已有就 409,原子写);
- `POST /api/userdata/{file}/move/{dest}?overwrite=false` 移动(目标已有就 409,目标的父目录会建)。

**不覆盖、不硬删**:写和移动一律 `overwrite=false`,撞名回 `{"conflict": true, "suggestion": …}`;ComfyUI 的 `DELETE` 是硬删,
这里从不调 —— 删除是挪进 `.mosael-trash/workflows/<删除时刻 UTC>/<原来的相对路径>`(在 `workflows/` 外面,ComfyUI 的侧栏和
插件的模型清单都不列它)。
"""

from __future__ import annotations

import calendar
import copy
import re
import time
import uuid
from collections import Counter
from typing import Any

import convert
import graph
import labels
import models
import workflows as described
from comfy_http import Comfy
from install import manager_version
from library import TRUSTED_SOURCES, _nodes, scan_workflow
from lines import ComfyError, say
from model_files import data_file, load_json, norm, save_json

#: 回收目录(相对用户目录)。
TRASH = ".mosael-trash/workflows"
#: 只在前端的节点:后端的 object_info 里永远没有,不是「缺」(ADR 0035 §5)。
VIRTUAL_NODES = frozenset({
    "Note", "MarkdownNote", "Reroute", "PrimitiveNode",
    # KJNodes
    "SetNode", "GetNode",
    # rgthree:只在前端的那几个(Seed、Power Lora Loader、Image Comparer 这类有后端,不在这里)
    "Fast Groups Bypasser (rgthree)", "Fast Groups Muter (rgthree)", "Fast Bypasser (rgthree)", "Fast Muter (rgthree)",
    "Fast Actions Button (rgthree)", "Label (rgthree)", "Bookmark (rgthree)", "Reroute (rgthree)", "Node Combiner (rgthree)",
    "Node Collector (rgthree)", "Mute / Bypass Relay (rgthree)", "Mute / Bypass Repeater (rgthree)",
    "Power Primitive (rgthree)",
})
#: 缩略图上最多画几个节点。
MAX_NODES = 400
#: Manager 的「节点类型 → 节点包」映射几 MB,一天取一次,记在持久目录里。
MAPPINGS_TTL_SECONDS = 24 * 3600
_BAD_SEGMENT = re.compile(r'[\x00-\x1f<>:"|?*\\]')
_TRASH_PATH = re.compile(r"^\.mosael-trash/workflows/(?P<stamp>\d{8}-\d{6})(-\d+)?/(?P<original>.+)$")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_MODEL_EXTENSIONS = (".safetensors", ".ckpt", ".pt", ".pth", ".bin", ".gguf", ".sft", ".onnx")


# --- 路径 ---------------------------------------------------------------------

def check_path(path: Any, locale: str) -> str:
    """`workflows/` 里的一张:相对路径、`.json`、`/` 分段,每段不空、不是 `.` / `..`、不以点开头、没有 Windows 不收的字符。
    宿主查过一遍,这里写之前再查一遍。"""
    text = str(path or "").strip()
    segments = text.split("/")
    if not text.lower().endswith(".json") or len(text) > 500 or any(
        not one or one in (".", "..") or one.startswith(".") or one != one.strip() or _BAD_SEGMENT.search(one)
        for one in segments
    ):
        raise ComfyError(say(locale, f"「{text}」不是一个能用的工作流路径", f"“{text}” is not a usable workflow path"))
    return text


def _trash_path(path: Any, locale: str) -> re.Match[str]:
    text = str(path or "").strip()
    found = _TRASH_PATH.match(text)
    if found is None or ".." in text.split("/"):
        raise ComfyError(say(locale, f"「{text}」不在回收目录里", f"“{text}” is not in the trash"))
    check_path(found.group("original"), locale)
    return found


def _free_name(wanted: str, taken: set[str]) -> str:
    """一个不撞名的建议:`a/人像.json` → `a/人像 (1).json`、`a/人像 (2).json`……"""
    stem = wanted[:-5]
    for index in range(1, 1000):
        candidate = f"{stem} ({index}).json"
        if candidate not in taken:
            return candidate
    return wanted


def _taken(comfy: Comfy) -> set[str]:
    return {str(item.get("path") or "") for item in comfy.workflow_listing()}


def _conflict(comfy: Comfy, wanted: str) -> dict[str, Any]:
    return {"conflict": True, "suggestion": _free_name(wanted, _taken(comfy))}


def _seconds(value: Any) -> float | None:
    """`/api/userdata` 的 `modified`:新版给毫秒,老版给秒。统一成秒。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value) / 1000 if value > 1e11 else float(value)


# --- 图摘要 ---------------------------------------------------------------------

def _pair(value: Any) -> tuple[float, float] | None:
    """`[x, y]`,或者老格式的 `{"0": x, "1": y}`。"""
    if isinstance(value, dict):
        value = [value.get("0"), value.get("1")]
    if isinstance(value, (list, tuple)) and len(value) >= 2 and all(
        isinstance(one, (int, float)) and not isinstance(one, bool) for one in value[:2]
    ):
        return float(value[0]), float(value[1])
    return None


def _role(class_type: str, object_info: dict[str, Any], missing: set[str]) -> str:
    """缩略图上着什么色:读素材的、加载模型的、采样、提示词、产出、注释、缺的、别的。"""
    if class_type in missing:
        return "missing"
    if class_type in ("Note", "MarkdownNote"):
        return "note"
    info = object_info.get(class_type) if isinstance(object_info.get(class_type), dict) else {}
    lowered = class_type.lower()
    if info.get("output_node") is True or class_type.startswith(("Save", "Preview")) or "videocombine" in lowered:
        return "output"
    if "loader" in lowered:
        return "model"
    if lowered.startswith("load") or any(mark in lowered for mark in ("loadimage", "loadvideo", "loadaudio")):
        return "input"
    if "sampler" in lowered:
        return "sampler"
    if "textencode" in lowered or "prompt" in lowered:
        return "text"
    return "other"


def _layout(ids: list[str], edges: list[tuple[str, str]]) -> dict[str, tuple[float, float]]:
    """没有位置的图(API 格式)按依赖自动排:每个节点放在「离源头最远那条路的长度」那一列,同一列从上往下。"""
    depth = {one: 0 for one in ids}
    incoming: dict[str, list[str]] = {one: [] for one in ids}
    for source, target in edges:
        if source in depth and target in depth and source != target:
            incoming[target].append(source)
    for _ in range(len(ids)):  # 最长路径;有环时到这个次数为止
        changed = False
        for target, sources in incoming.items():
            best = max((depth[one] + 1 for one in sources), default=0)
            if best > depth[target]:
                depth[target], changed = best, True
        if not changed:
            break
    rows: Counter[int] = Counter()
    out: dict[str, tuple[float, float]] = {}
    for one in sorted(ids, key=lambda value: (depth[value], int(value) if value.isdigit() else 0, value)):
        out[one] = (depth[one] * 380.0, rows[depth[one]] * 170.0)
        rows[depth[one]] += 1
    return out


def graph_summary(source: dict[str, Any], object_info: dict[str, Any], missing: set[str]) -> dict[str, Any]:
    """画缩略图用的图摘要(根图;子图里的不展开):节点、连线(节点下标对)、分组。"""
    if isinstance(source.get("nodes"), list):
        raw_nodes = [one for one in source["nodes"] if isinstance(one, dict)]
        ids = [str(one.get("id")) for one in raw_nodes]
        edges: list[tuple[str, str]] = []
        for link in source.get("links") or []:
            if isinstance(link, list) and len(link) >= 4:
                edges.append((str(link[1]), str(link[3])))
            elif isinstance(link, dict):
                edges.append((str(link.get("origin_id")), str(link.get("target_id"))))
        placed = {str(one.get("id")): _pair(one.get("pos")) for one in raw_nodes}
        auto = not any(placed.values())
        positions = _layout(ids, edges) if auto else placed
        nodes = []
        for one in raw_nodes[:MAX_NODES]:
            node_id = str(one.get("id"))
            where = positions.get(node_id) or (0.0, 0.0)
            size = _pair(one.get("size")) or (300.0, 120.0)
            class_type = str(one.get("type") or "")
            nodes.append({"id": node_id, "x": where[0], "y": where[1], "w": size[0], "h": size[1],
                          "role": _role(class_type, object_info, missing), "muted": one.get("mode") in (2, 4),
                          "title": str(one.get("title") or class_type)[:120]})
        groups = []
        for one in source.get("groups") or []:
            box = one.get("bounding") if isinstance(one, dict) else None
            if isinstance(box, list) and len(box) >= 4 and all(isinstance(v, (int, float)) for v in box[:4]):
                groups.append({"x": float(box[0]), "y": float(box[1]), "w": float(box[2]), "h": float(box[3]),
                               "title": str(one.get("title") or "")[:120], "color": str(one.get("color") or "")[:20]})
        total = len(raw_nodes)
    else:
        api = {str(key): value for key, value in source.items() if isinstance(value, dict) and "class_type" in value}
        ids = list(api)
        edges = [(str(value[0]), node_id) for node_id, node in api.items()
                 for value in (node.get("inputs") or {}).values() if isinstance(value, list) and len(value) == 2]
        positions, auto, groups, total = _layout(ids, edges), True, [], len(ids)
        nodes = []
        for node_id in sorted(ids, key=lambda value: (positions[value][0], positions[value][1]))[:MAX_NODES]:
            class_type = str(api[node_id].get("class_type") or "")
            meta = api[node_id].get("_meta") if isinstance(api[node_id].get("_meta"), dict) else {}
            nodes.append({"id": node_id, "x": positions[node_id][0], "y": positions[node_id][1], "w": 300.0, "h": 120.0,
                          "role": _role(class_type, object_info, missing), "muted": False,
                          "title": str(meta.get("title") or class_type)[:120]})
    index = {node["id"]: number for number, node in enumerate(nodes)}
    links = [[index[source_id], index[target_id]] for source_id, target_id in edges if source_id in index and target_id in index]
    for node in nodes:
        del node["id"]
    return {"nodes": nodes, "links": links, "groups": groups, "auto_layout": auto, "truncated": total > MAX_NODES}


# --- 缺什么 ---------------------------------------------------------------------

def missing_types(source: dict[str, Any], object_info: dict[str, Any]) -> Counter[str]:
    """object_info 里没有、又不是只在前端的节点类型,各几个(子图里的也算;子图实例、老式组节点不是节点类型)。"""
    subgraphs = {str(one.get("id")) for one in (source.get("definitions") or {}).get("subgraphs") or [] if isinstance(one, dict)}
    found: Counter[str] = Counter()
    for node in _nodes(source):
        class_type = str(node.get("type") or node.get("class_type") or "")
        if not class_type or class_type in object_info or class_type in VIRTUAL_NODES or class_type in subgraphs:
            continue
        if _UUID.match(class_type) or class_type.startswith(("workflow>", "workflow/")):
            continue
        found[class_type] += 1
    return found


def _packs(comfy: Comfy, types: list[str]) -> dict[str, list[dict[str, Any]]]:
    """节点类型 → 可能出自的节点包(ComfyUI-Manager 的映射),装没装。没有 Manager → 空。"""
    if not types or not manager_version(comfy):
        return {}
    cache_path = data_file(comfy, "node-mappings")
    cached = load_json(cache_path)
    mappings = cached.get("mappings") if isinstance(cached.get("mappings"), dict) else None
    if mappings is None or float(cached.get("at") or 0) < time.time() - MAPPINGS_TTL_SECONDS:
        try:
            fetched = comfy.get("/v2/customnode/getmappings", {"mode": "cache"})
        except ComfyError:
            fetched = None
        if isinstance(fetched, dict):
            mappings = fetched
            save_json(cache_path, {"at": time.time(), "mappings": mappings})
    try:
        installed = comfy.get("/v2/customnode/installed")
    except ComfyError:
        installed = {}
    have = {str(key).lower() for key in (installed or {})} if isinstance(installed, dict) else set()
    for value in (installed or {}).values() if isinstance(installed, dict) else []:
        if isinstance(value, dict):
            have |= {str(value.get(key)).lower() for key in ("cnr_id", "aux_id") if value.get(key)}
    out: dict[str, list[dict[str, Any]]] = {}
    for class_type in types:
        found = []
        for pack, entry in (mappings or {}).items():
            names = entry[0] if isinstance(entry, list) and entry and isinstance(entry[0], list) else []
            meta = entry[1] if isinstance(entry, list) and len(entry) > 1 and isinstance(entry[1], dict) else {}
            pattern = meta.get("nodename_pattern")
            matched = class_type in names
            if not matched and isinstance(pattern, str):
                try:
                    matched = re.match(pattern, class_type) is not None
                except re.error:
                    matched = False
            if matched:
                short = str(pack).rstrip("/").removesuffix(".git").rsplit("/", 1)[-1].lower()
                found.append({"id": str(pack), "title": str(meta.get("title_aux") or pack),
                              "installed": str(pack).lower() in have or short in have})
        out[class_type] = found[:10]
    return out


def _choices(spec: Any) -> list[Any] | None:
    """一个下拉的可选值:老写法 `[[…], {…}]`,新写法(ComfyUI 0.38 的 V3 节点)`["COMBO", {"options": […]}]`。"""
    if not isinstance(spec, list) or not spec:
        return None
    if isinstance(spec[0], list):
        return spec[0]
    if spec[0] == "COMBO" and len(spec) > 1 and isinstance(spec[1], dict) and isinstance(spec[1].get("options"), list):
        return spec[1]["options"]
    return None


def model_options(object_info: dict[str, Any]) -> dict[str, set[str]]:
    """每个模型目录里有哪些文件 —— 从 object_info 里选模型文件的那些下拉读(ComfyUI 拿目录里的文件当可选值),不必再问一遍。"""
    out: dict[str, set[str]] = {}
    for class_type, info in object_info.items():
        inputs = info.get("input") if isinstance(info, dict) and isinstance(info.get("input"), dict) else {}
        for group in ("required", "optional"):
            for name, spec in (inputs.get(group) or {}).items():
                folder = labels.model_folder(class_type, name)
                choices = _choices(spec) if folder else None
                if choices is not None:
                    out.setdefault(folder, set()).update(norm(str(one)) for one in choices)
    return out


def _models(api: dict[str, Any], source: dict[str, Any], options: dict[str, set[str]]
            ) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """(用到的模型文件和在不在, 缺的模型)。转得过来的看节点上选模型文件的那几格;再加上工作流声明的下载地址。"""
    _used, declared = scan_workflow(source)
    urls = {(one["folder"], one["name"]): one["url"] for one in declared}
    picked: list[tuple[str, str]] = []
    for node in api.values():
        class_type = str(node.get("class_type") or "")
        for name, value in (node.get("inputs") or {}).items():
            folder = labels.model_folder(class_type, name)
            if folder and isinstance(value, str) and value.strip():
                picked.append((folder, norm(value)))
    if not api:
        # 转不过来(比如缺节点):看节点上写着的、长得像模型文件的名字在哪个目录里
        for value in _used:
            if value.lower().endswith(_MODEL_EXTENSIONS):
                folder = next((name for name, files in options.items() if value in files), "")
                if folder:
                    picked.append((folder, value))
    picked += list(urls)
    seen: set[tuple[str, str]] = set()
    found: list[dict[str, Any]] = []
    missing: list[dict[str, str]] = []
    for folder, name in picked:
        if (folder, name) in seen:
            continue
        seen.add((folder, name))
        present = name in options.get(folder, set())
        found.append({"folder": folder, "name": name, "present": present})
        if not present:
            url = urls.get((folder, name), "")
            missing.append({"folder": folder, "name": name, "url": url if url.startswith(TRUSTED_SOURCES) else ""})
    return found, missing


# --- op ---------------------------------------------------------------------------

def _trash(comfy: Comfy) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in comfy.userdata_listing(TRASH):
        path = f"{TRASH}/{item.get('path')}"
        found = _TRASH_PATH.match(path)
        if found is None:
            continue
        deleted = calendar.timegm(time.strptime(found.group("stamp"), "%Y%m%d-%H%M%S"))
        out.append({"path": path, "deleted_at": float(deleted)})
    return sorted(out, key=lambda one: -one["deleted_at"])


def workflows(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    object_info = comfy.object_info()
    options = model_options(object_info)
    listing = {str(item.get("path") or ""): item for item in comfy.workflow_listing()}
    saved, others = comfy.saved_files()
    rows: list[tuple[dict[str, Any], dict[str, Any], Counter[str]]] = []
    lacking: set[str] = set()
    for path in saved:
        item = listing.get(path) or {}
        row: dict[str, Any] = {"path": path, "size": item.get("size"), "modified": _seconds(item.get("modified")),
                               "problem": ""}
        try:
            source = comfy.fetch_workflow(path)
        except ComfyError as exc:
            rows.append(({**row, "problem": str(exc)}, {}, Counter()))
            continue
        missing = missing_types(source, object_info)
        lacking |= set(missing)
        rows.append((row, source, missing))
    packs = _packs(comfy, sorted(lacking))
    out: list[dict[str, Any]] = []
    for row, source, missing in rows:
        if not source:
            out.append(row)
            continue
        row["node_count"] = len(source["nodes"]) if isinstance(source.get("nodes"), list) else \
            len([one for one in source.values() if isinstance(one, dict) and "class_type" in one])
        row["graph"] = graph_summary(source, object_info, set(missing))
        row["missing_nodes"] = [{"type": name, "count": count, "packs": packs.get(name, [])}
                                for name, count in sorted(missing.items())]
        api: dict[str, Any] = {}
        try:
            api = graph.live(convert.to_api(source, object_info, locale), object_info)
        except Exception as exc:  # noqa: BLE001 — 一张转不过来,照样列出来、带着原因
            row["problem"] = str(exc) or type(exc).__name__
        if api:
            info = described.inspect(row["path"], models.label_of(row["path"]), api, object_info,
                                     convert.titles_of(api), locale)
            row.update({"kind": info["kind"], "inputs": info["inputs"], "parameters": info["parameters"],
                        "outputs": info["outputs"]})
        elif not row.get("problem"):
            row["problem"] = say(locale, "工作流是空的", "The workflow is empty")
        if missing and not row.get("problem"):
            names = "、".join(sorted(missing))
            row["problem"] = say(locale, f"这台 ComfyUI 上没有这几种节点:{names}。装上对应的节点包才跑得了",
                                 f"This ComfyUI lacks these node types: {', '.join(sorted(missing))}. "
                                 "Install the node packs that provide them to run it")
        row["models"], row["missing_models"] = _models(api, source, options)
        out.append(row)
    return {
        "workflows": out,
        "others": [{"path": path, "reason": models._not_a_workflow(path, locale)} for path in others],
        "trash": _trash(comfy),
        "manager": {"version": manager_version(comfy)},
        #: 「在编辑器里打开」开的就是这台服务器的网页界面(宿主只认 http(s));打开具体哪一张由 Mosael 在页面里做
        "editor": {"kind": "comfyui", "url": comfy.base},
    }


def workflow(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    return {"content": comfy.fetch_workflow(check_path(payload.get("path"), locale))}


def copy_workflow(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """复制一张:副本换一个新的图 id(新版前端保存时写进去的 UUID —— 两张同 id 的图,插件给它们起的工具名会撞)。"""
    path, new_path = check_path(payload.get("path"), locale), check_path(payload.get("new_path"), locale)
    content = copy.deepcopy(comfy.fetch_workflow(path))
    if isinstance(content.get("id"), str):
        content["id"] = str(uuid.uuid4())
    if not comfy.write_userdata(f"workflows/{new_path}", content):
        return _conflict(comfy, new_path)
    return {"path": new_path}


def rename_workflow(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    path, new_path = check_path(payload.get("path"), locale), check_path(payload.get("new_path"), locale)
    if path == new_path:
        return {"path": path}
    if not comfy.move_userdata(f"workflows/{path}", f"workflows/{new_path}"):
        return _conflict(comfy, new_path)
    return {"path": new_path}


def trash_workflow(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """挪进回收目录。同一秒删两张同名的(极少)就在时刻后面加序号,不撞。"""
    path = check_path(payload.get("path"), locale)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    for attempt in range(20):
        target = f"{TRASH}/{stamp}{f'-{attempt}' if attempt else ''}/{path}"
        if comfy.move_userdata(f"workflows/{path}", target):
            return {"path": target}
    raise ComfyError(say(locale, "回收目录里撞名太多次,没挪成", "Too many name clashes in the trash; nothing was moved"))


def restore_workflow(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    found = _trash_path(payload.get("path"), locale)
    new_path = check_path(payload.get("new_path") or found.group("original"), locale)
    if not comfy.move_userdata(found.group(0), f"workflows/{new_path}"):
        return _conflict(comfy, new_path)
    return {"path": new_path}
