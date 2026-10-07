"""工作流库(ADR 0035):这台 ComfyUI 上存着的工作流 —— 列出、取原文、复制、改名、挪进 / 挪出回收目录;文件夹。

宿主按 `op` 问(见 main._generation):

    {"op": "workflows"}                                → 全部工作流(图摘要、识别出的输入 / 参数 / 输出、用到的模型、缺什么)
                                                          + 子目录(空的也在)+ 不是工作流的文件 + 回收目录里的 + Manager 的版本
    {"op": "workflow", "path"}                         → 一张的原文
    {"op": "copy_workflow", "path", "new_path"}        → 复制(副本换一个新的图 id)
    {"op": "rename_workflow", "path", "new_path"}      → 改名 / 挪目录(「移动到…」、拖到左边的文件夹上也是它)
    {"op": "trash_workflow", "path"}                   → 「删除」:挪进回收目录
    {"op": "restore_workflow", "path", "new_path"}     → 从回收目录挪回去
    {"op": "make_folder", "path"}                      → 新建文件夹(ADR 0035 后续「文件夹」)
    {"op": "rename_folder", "path", "new_path"}        → 文件夹改名 / 挪到别的文件夹里(里面的一切跟着走)
    {"op": "trash_folder", "path"}                     → 删除文件夹:**只删空的**(挪进回收目录);里面还有文件回 not_empty
    {"op": "app", "path"}                              → 一张的应用表单(ADR 0038):全部能填的项、文件里的标记、读到时的改动时间
    {"op": "annotate", "path", "modified", "app", "results"} → 只改 `mosael` 那几处标记,**覆盖写**;改动时间对不上回 stale

导入、装缺的节点包、重启在 workflow_import。

用到的 ComfyUI 接口(0.38.0,写 / 移动照源码 app/user_manager.py 核对,见 ADR 0035 的表):

- `GET /api/userdata?dir=…&recurse=true&full_info=true` 列文件(glob:只列文件、跳过隐藏的 —— ComfyUI 自己的工作流侧栏
  就是照它摆出文件夹的);`GET /api/v2/userdata?path=…` 连目录一起列(空目录也在);`GET /api/userdata/{file}` 取一份;
- `POST /api/userdata/{file}?overwrite=false` 写一份(已有就 409,原子写;父目录不存在会建);
- `POST /api/userdata/{file}/move/{dest}?overwrite=false` 移动(`shutil.move`,目录也挪得动;目标已有就 409,目标的父目录
  会建,源不在了 404)。

**不覆盖、不硬删**:写和移动一律 `overwrite=false`,撞名回 `{"conflict": true, "suggestion": …}`;ComfyUI 的 `DELETE` 是硬删,
这里从不调 —— 删除是挪进 `.mosael-trash/workflows/<删除时刻 UTC>/<原来的相对路径>`(在 `workflows/` 外面,ComfyUI 的侧栏和
插件的模型清单都不列它)。**唯一的例外是 `annotate`**(ADR 0038 §2):它覆盖写一张已有的工作流,但只改 `mosael` 那几处标记
(app_form.apply),而且带着读到时的改动时间来 —— 那台机器上的文件在这之间被改过就不写,回 `{"stale": true}`。

**文件夹**就是 `workflows/` 里的子目录 —— 和 ComfyUI 自己的侧栏同一份,不另记。ComfyUI 没有「建目录」「删目录」的接口:
新建是往里写一个隐藏的占位文件(`.mosael-folder`;写文件时 ComfyUI 把父目录建出来,ComfyUI 的侧栏和这里都不列隐藏文件);
删除只认空的(里面没有一个看得见的文件),挪进回收目录 —— 要删的文件夹里还有东西,先挪走或一张张删(各自确认、各自能恢复),
一下子带走一整个文件夹的工作流太容易误伤。改动前都现查一遍那台机器(源不在了、目标被占了、里面又有了东西),不照界面
手里那份旧列表办。
"""

from __future__ import annotations

import calendar
import copy
import re
import time
import uuid
from collections import Counter
from typing import Any

import app_form
import convert
import graph
import json_style
import labels
import models
import workflows as described
from comfy_http import Comfy, is_workflow_path
from install import manager_version
from library import TRUSTED_SOURCES, _nodes, scan_workflow
from lines import ComfyError, say
from model_files import data_file, load_json, norm, save_json

#: 回收目录(相对用户目录)。
TRASH = ".mosael-trash/workflows"
#: 新建的(还空着的)文件夹里那个占位文件。隐藏的:ComfyUI 的侧栏、插件、Mosael 都不列它;有了工作流以后留着也无妨。
FOLDER_MARKER = ".mosael-folder"
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


def check_folder(path: Any, locale: str) -> str:
    """`workflows/` 里的一个子目录:和工作流路径同一套分段规则,只是不以 `.json` 结尾(那像一张工作流)。"""
    text = str(path or "").strip()
    segments = text.split("/")
    if not text or text.lower().endswith(".json") or len(text) > 400 or any(
        not one or one in (".", "..") or one.startswith(".") or one != one.strip() or _BAD_SEGMENT.search(one)
        for one in segments
    ):
        raise ComfyError(say(locale, f"「{text}」不是一个能用的文件夹名", f"“{text}” is not a usable folder name"))
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


def folders(comfy: Comfy, files: list[str]) -> list[str]:
    """`workflows/` 里的子目录(相对 `workflows/`,按名字排):有文件的那几个的各级父目录,加上 `/api/v2/userdata` 列得出的
    (空的也在,老版本 ComfyUI 没有这个接口就只有前一半)。隐藏的(以点开头的某一段)不算。"""
    found: set[str] = set()
    for path in files:
        parts = path.split("/")[:-1]
        found.update("/".join(parts[:depth]) for depth in range(1, len(parts) + 1))
    for item in comfy.userdata_tree("workflows") or []:
        relative = str(item.get("path") or "")
        if item.get("type") == "directory" and relative.startswith("workflows/"):
            found.add(relative[len("workflows/"):])
    return sorted((one for one in found if one and not any(part.startswith(".") for part in one.split("/"))),
                  key=lambda one: (one.lower(), one))


def _folders_now(comfy: Comfy) -> tuple[list[str], list[str]]:
    """(那台机器上**现在**的子目录, 看得见的文件)—— 改文件夹之前现查,不照界面手里那份列表。"""
    saved, others = comfy.saved_files()
    files = saved + others
    return folders(comfy, files), files


def _free_folder(wanted: str, taken: set[str]) -> str:
    """一个不撞名的文件夹名(不分大小写比 —— 那台机器可能是 Windows):`人像` → `人像 (1)`、`人像 (2)`……"""
    for index in range(1, 1000):
        candidate = f"{wanted} ({index})"
        if candidate.lower() not in taken:
            return candidate
    return wanted


def _gone_folder(locale: str, path: str) -> ComfyError:
    return ComfyError(say(locale, f"ComfyUI 里已经没有文件夹「{path}」了", f"ComfyUI no longer has the folder “{path}”."))


def _move(comfy: Comfy, source: str, dest: str, gone: ComfyError) -> bool:
    """挪一份(文件或目录),不覆盖:目标被占了回 False;源不在了(ComfyUI 回 404)抛 `gone` —— 界面手里的列表旧了。"""
    try:
        return comfy.move_userdata(source, dest)
    except ComfyError as exc:
        if exc.status == 404:
            raise gone from exc
        raise


def _to_trash(comfy: Comfy, path: str, gone: ComfyError, locale: str) -> str:
    """把 `workflows/<path>`(一张或一个文件夹)挪进回收目录。同一秒删两个同名的(极少)就在时刻后面加序号,不撞。"""
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
    for attempt in range(20):
        target = f"{TRASH}/{stamp}{f'-{attempt}' if attempt else ''}/{path}"
        if _move(comfy, f"workflows/{path}", target, gone):
            return target
    raise ComfyError(say(locale, "回收目录里撞名太多次,没挪成", "Too many name clashes in the trash; nothing was moved"))


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


def manager_mappings(comfy: Comfy) -> dict[str, Any] | None:
    """ComfyUI-Manager 的「节点包 → 它提供的节点类型」映射(几 MB,一天取一次,记在持久目录里)。没有 Manager → None。"""
    if not manager_version(comfy):
        return None
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
    return mappings


def installed_packs(comfy: Comfy) -> dict[str, dict[str, Any]] | None:
    """Manager 说装了哪些节点包:目录名 → `{ver, cnr_id, aux_id, enabled}`。没有 Manager(或它答不上)→ None。"""
    try:
        found = comfy.get("/v2/customnode/installed")
    except ComfyError:
        return None
    return {str(key): value for key, value in found.items() if isinstance(value, dict)} if isinstance(found, dict) else None


def pack_ids(installed: dict[str, dict[str, Any]]) -> set[str]:
    """装着的包能叫的名字(小写):目录名、注册表 id、git 的仓库名。"""
    have = {key.lower() for key in installed}
    for value in installed.values():
        have |= {str(value.get(key)).lower() for key in ("cnr_id",) if value.get(key)}
        if value.get("aux_id"):
            have.add(str(value["aux_id"]).rstrip("/").removesuffix(".git").rsplit("/", 1)[-1].lower())
    return have


def mapping_short(pack: str) -> str:
    """映射里一个包的键(注册表 id,或者仓库地址)→ 比较用的那个短名字(小写的仓库名)。"""
    return str(pack).rstrip("/").removesuffix(".git").rsplit("/", 1)[-1].lower()


def provides(entry: Any, class_type: str) -> bool:
    """映射里的这个包提供不提供这个节点类型(列着,或者对得上它的 `nodename_pattern`)。"""
    names = entry[0] if isinstance(entry, list) and entry and isinstance(entry[0], list) else []
    meta = entry[1] if isinstance(entry, list) and len(entry) > 1 and isinstance(entry[1], dict) else {}
    if class_type in names:
        return True
    pattern = meta.get("nodename_pattern")
    if not isinstance(pattern, str):
        return False
    # 照 Manager 自己的认法:不锚在开头(它找缺的节点包用 re.search,前端用 RegExp.test)。rgthree 的写法是
    # 「 \(rgthree\)$」—— 用 re.match 的话,「Any Switch (rgthree)」这类节点永远认不出出自它
    try:
        return re.search(pattern, class_type) is not None
    except re.error:
        return False


def _packs(comfy: Comfy, types: list[str]) -> dict[str, list[dict[str, Any]]]:
    """节点类型 → 可能出自的节点包(ComfyUI-Manager 的映射),装没装。没有 Manager → 空。"""
    if not types:
        return {}
    mappings = manager_mappings(comfy)
    if mappings is None:
        return {}
    have = pack_ids(installed_packs(comfy) or {})
    out: dict[str, list[dict[str, Any]]] = {}
    for class_type in types:
        found = []
        for pack, entry in mappings.items():
            if provides(entry, class_type):
                meta = entry[1] if isinstance(entry, list) and len(entry) > 1 and isinstance(entry[1], dict) else {}
                found.append({"id": str(pack), "title": str(meta.get("title_aux") or pack),
                              "installed": str(pack).lower() in have or mapping_short(pack) in have})
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
    """(用到的模型文件和在不在, 缺的模型)。转得过来的看节点上选模型文件的那几格;再加上工作流声明的下载地址(只收节点
    当前真在用的,按转出来的图判,见 library.scan_workflow)。"""
    _used, declared = scan_workflow(source, api or None)
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
        if found is None or not is_workflow_path(found.group("original")):
            continue  # 删掉的空文件夹里那个占位文件之类:不是一张工作流,回收站里不列
        deleted = calendar.timegm(time.strptime(found.group("stamp"), "%Y%m%d-%H%M%S"))
        out.append({"path": path, "deleted_at": float(deleted)})
    return sorted(out, key=lambda one: -one["deleted_at"])


def describe(row: dict[str, Any], source: dict[str, Any], object_info: dict[str, Any], options: dict[str, set[str]],
             comfy: Comfy, locale: str, *, missing: Counter[str] | None = None,
             packs: dict[str, list[dict[str, Any]]] | None = None) -> dict[str, Any]:
    """一张工作流的样子,补进 `row`:节点数、图摘要、缺的节点(和节点包)、识别出的输入 / 参数 / 输出、用到的模型和缺的模型、
    跑不了的原因。列工作流库和导入前的预览是同一份(列的时候缺什么、节点包一次问完,传进来)。"""
    missing = missing if missing is not None else missing_types(source, object_info)
    packs = packs if packs is not None else _packs(comfy, sorted(missing))
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
        titles = convert.titles_of(api)
        marks = app_form.read(source)
        form, invalid = app_form.resolve(marks, api, object_info, titles)
        # 识别出的输入 / 参数说的是这张图的表单:有应用表单就是作者挑的那几项(和生成、工具同一张表)
        info = described.inspect(row["path"], models.label_of(row["path"]), api, object_info, titles, locale, form)
        row.update({"kind": info["kind"], "inputs": info["inputs"], "parameters": info["parameters"],
                    "outputs": info["outputs"], "app": app_form.summary(marks, form, invalid, locale)})
    elif not row.get("problem"):
        row["problem"] = say(locale, "工作流是空的", "The workflow is empty")
    if missing and not row.get("problem"):
        names = "、".join(sorted(missing))
        row["problem"] = say(locale, f"这台 ComfyUI 上没有这几种节点:{names}。装上对应的节点包才跑得了",
                             f"This ComfyUI lacks these node types: {', '.join(sorted(missing))}. "
                             "Install the node packs that provide them to run it")
    row["models"], row["missing_models"] = _models(api, source, options)
    return row


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
    out = [describe(row, source, object_info, options, comfy, locale, missing=missing, packs=packs) if source else row
           for row, source, missing in rows]
    return {
        "workflows": out,
        #: 左边那一列的文件夹树(ComfyUI 自己的侧栏也按子目录分),空的也列 —— 刚新建、还没挪进去东西的那种
        "folders": folders(comfy, saved + others),
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
    """改名、挪到别的文件夹(「移动到…」、拖到左边的文件夹上)。目标文件夹不在会被建出来;这张已经不在了说清楚。"""
    path, new_path = check_path(payload.get("path"), locale), check_path(payload.get("new_path"), locale)
    if path == new_path:
        return {"path": path}
    if not _move(comfy, f"workflows/{path}", f"workflows/{new_path}", _gone(locale, path)):
        return _conflict(comfy, new_path)
    return {"path": new_path}


def trash_workflow(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """挪进回收目录。"""
    path = check_path(payload.get("path"), locale)
    return {"path": _to_trash(comfy, path, _gone(locale, path), locale)}


def restore_workflow(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    found = _trash_path(payload.get("path"), locale)
    new_path = check_path(payload.get("new_path") or found.group("original"), locale)
    gone = ComfyError(say(locale, "回收目录里已经没有这一张了", "That workflow is no longer in the trash."))
    if not _move(comfy, found.group(0), f"workflows/{new_path}", gone):
        return _conflict(comfy, new_path)
    return {"path": new_path}


# --- 文件夹 ---------------------------------------------------------------------------

def make_folder(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """新建一个文件夹(可以带上级:`人像/草稿`)。ComfyUI 没有建目录的接口:往里面写一个隐藏的占位文件,写文件时 ComfyUI
    把父目录建出来。已经有了(不分大小写比)回 conflict 和一个建议名。"""
    path = check_folder(payload.get("path"), locale)
    existing, _files = _folders_now(comfy)
    taken = {one.lower() for one in existing}
    if path.lower() in taken:
        return {"conflict": True, "suggestion": _free_folder(path, taken)}
    marker = {"created_by": "Mosael", "note": "Keeps this folder while it is empty. Safe to delete."}
    if not comfy.write_userdata(f"workflows/{path}/{FOLDER_MARKER}", marker):
        return {"conflict": True, "suggestion": _free_folder(path, taken | {path.lower()})}
    return {"path": path}


def rename_folder(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """文件夹改名,或者挪到别的文件夹里(`new_path` 带上级):整个目录一次挪过去,里面的工作流、子文件夹跟着走 —— 它们的
    路径都变了,宿主让生成目录重拉。不覆盖:目标已经有了回 conflict。只改大小写(`video` → `Video`)在不分大小写的磁盘上
    「目标已经有了」,先挪到一个临时名字再挪过去。"""
    path, new_path = check_folder(payload.get("path"), locale), check_folder(payload.get("new_path"), locale)
    if path == new_path:
        return {"path": path}
    if new_path.lower().startswith(path.lower() + "/"):
        raise ComfyError(say(locale, f"不能把「{path}」挪进它自己里面", f"“{path}” can't be moved into itself."))
    existing, _files = _folders_now(comfy)
    taken = {one.lower() for one in existing}
    gone = _gone_folder(locale, path)
    if path not in existing:
        raise gone
    case_only = new_path.lower() == path.lower()
    if not case_only and new_path.lower() in taken:
        return {"conflict": True, "suggestion": _free_folder(new_path, taken)}
    if _move(comfy, f"workflows/{path}", f"workflows/{new_path}", gone):
        return {"path": new_path}
    if not case_only:
        return {"conflict": True, "suggestion": _free_folder(new_path, taken | {new_path.lower()})}
    parent = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
    temporary = f"workflows/{parent}.mosael-renaming-{uuid.uuid4().hex[:8]}"
    if not _move(comfy, f"workflows/{path}", temporary, gone):
        raise ComfyError(say(locale, "临时名字撞上了,没改成,再试一次", "The temporary name clashed; nothing changed. Try again."))
    if _move(comfy, temporary, f"workflows/{new_path}", gone):
        return {"path": new_path}
    _move(comfy, temporary, f"workflows/{path}", gone)  # 挪回去:什么都没变
    return {"conflict": True, "suggestion": _free_folder(new_path, taken | {new_path.lower()})}


def trash_folder(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """删除一个文件夹:**只删空的**(里面没有一个看得见的文件,空的子文件夹不算),挪进回收目录 —— ComfyUI 删不了目录,
    也不该一下子带走一整个文件夹的工作流。挪之前现查:里面有了东西(界面那份列表之后在 ComfyUI 里存进去的)回
    `{"not_empty": true, "count": 几个文件}`,什么都不动。"""
    path = check_folder(payload.get("path"), locale)
    existing, files = _folders_now(comfy)
    if path not in existing:
        raise _gone_folder(locale, path)
    inside = [one for one in files if one.lower().startswith(path.lower() + "/")]
    if inside:
        return {"not_empty": True, "count": len(inside)}
    return {"path": _to_trash(comfy, path, _gone_folder(locale, path), locale)}


# --- 应用表单(ADR 0038 §2)-----------------------------------------------------------

def _modified(comfy: Comfy, path: str) -> float | None:
    """这张工作流在那台机器上的改动时间(秒);没有这张了是 None。"""
    for item in comfy.workflow_listing():
        if str(item.get("path") or "") == path:
            return _seconds(item.get("modified"))
    return None


def _same_time(left: float | None, right: Any) -> bool:
    return left is not None and isinstance(right, (int, float)) and not isinstance(right, bool) and abs(left - right) < 5e-4


def _gone(locale: str, path: str) -> ComfyError:
    return ComfyError(say(locale, f"ComfyUI 里已经没有工作流「{path}」了", f"ComfyUI no longer has the workflow “{path}”."))


def _read(comfy: Comfy, path: str, locale: str) -> tuple[dict[str, Any], float]:
    """原文和**读到它时**的改动时间:取之前、取之后各看一眼改动时间,对不上(正好在这时被存了)就再取一遍。"""
    for _ in range(3):
        before = _modified(comfy, path)
        if before is None:
            raise _gone(locale, path)
        source = comfy.fetch_workflow(path)
        if _same_time(before, _modified(comfy, path)):
            return source, before
    raise ComfyError(say(locale, f"「{path}」一直在被改,过一会儿再试", f"“{path}” keeps changing; try again in a moment."))


def _item_out(item: dict[str, Any]) -> dict[str, Any]:
    """编辑器要的那一项:锚点、种类、名字、节点是谁(给人看的节点名、类名)、ComfyUI 给这一格的说明、常用与否、JSON Schema
    片段(下拉的全部可选值,收窄时从里面挑)。"""
    return {key: item[key] for key in ("key", "node", "input", "kind", "role", "media", "folder", "title", "node_title",
                                       "node_label", "hint", "class_type", "common", "schema") if key in item}


def live_graph(payload: dict[str, Any], locale: str) -> dict[str, Any]:
    """宿主带来的**画布上现在这张**(工作台,ADR 0038 §3):界面格式的图,有 `nodes` 才认。"""
    content = payload.get("content")
    if not isinstance(content, dict) or not isinstance(content.get("nodes"), list):
        raise ComfyError(say(locale, "画布上的图不是界面格式的工作流", "The canvas graph is not a UI-format workflow."))
    return content


def app(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """一张工作流的应用表单,给编辑器用:这张图**全部能填的项**(graph.items)、交回结果的输出节点(标「以后只要这张」用)、
    文件里的标记(对不上的带着原因)、读到时的改动时间(`annotate` 要带着它来)。API 格式的文件放不了标记(`editable: false`)。

    带着 `content`(工作台画布上现在这张,含没存的改动)来就不读文件:同样的回答,没有路径和改动时间 —— 改的是画布,
    存盘是 ComfyUI 自己的保存。

    `names`:这张图里每个会跑的节点给人看的名字(`{"zh", "en"}`,和表单项、「结果取自」同一种叫法,见 labels.node_name)。
    工作台的「运行与结果」按节点号说正在跑哪个、产出来自哪个,用的就是它 —— 不再是 `PreviewImage #12` 这种类名。"""
    if payload.get("content") is not None:
        path, source, modified = "", live_graph(payload, locale), None
    else:
        path = check_path(payload.get("path"), locale)
        source, modified = _read(comfy, path, locale)
    object_info = comfy.object_info()
    api = graph.live(convert.to_api(source, object_info, locale), object_info)
    titles = convert.titles_of(api)
    found = graph.items(api, object_info, titles)
    marks = app_form.read(source)
    form, invalid = app_form.resolve(marks, api, object_info, titles, found)
    kind = graph.kind_of(api)
    return {
        "path": path,
        "modified": modified,
        "kind": kind,
        "editable": isinstance(source.get("nodes"), list),
        "items": [_item_out(item) for item in found],
        "outputs": graph.generation_nodes(api, kind, object_info, titles),
        "names": {node_id: labels.node_name(str(node.get("class_type", "")), titles.get(node_id, ""), object_info)
                  for node_id, node in api.items()},
        "app": app_form.summary(marks, form, invalid, locale),
    }


def annotate(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    """改一张工作流的应用表单和结果标记:**只改 `mosael` 那几处**(app_form.apply),覆盖写回那台机器。

    带着读到时的改动时间(`modified`)来:那台机器上的文件在这之间被改过(在 ComfyUI 里存过、别人改过)就不写,回
    `{"stale": true, "modified": 现在的}` —— 宿主翻成 409,界面说「它刚在 ComfyUI 里改过,重新打开再改」。
    `app`:`{title, description, items: [{node, input, label?, main?, choices?}]}`,顺序就是表单的顺序;`null` 去掉应用表单。
    `results`:标成结果的输出节点(「以后只要这张」)。成了回 `{"path", "modified"}`(写完之后的改动时间,接着改用它)。
    """
    path = check_path(payload.get("path"), locale)
    app = payload.get("app")
    if app is not None and not isinstance(app, dict):
        raise ComfyError(say(locale, "应用表单的形状不对", "The app form is malformed."))
    results = payload.get("results") or []
    if not isinstance(results, list) or len(results) > app_form.MAX_RESULTS:
        raise ComfyError(say(locale, "标成结果的节点形状不对", "The result nodes are malformed."))
    current = _modified(comfy, path)
    if current is None:
        raise _gone(locale, path)
    if not _same_time(current, payload.get("modified")):
        return {"stale": True, "modified": current}
    source, text = comfy.fetch_workflow_text(path)
    if not _same_time(_modified(comfy, path), current):
        return {"stale": True, "modified": _modified(comfy, path)}
    updated = app_form.apply(source, app, [str(one) for one in results], locale)
    # 照原来的排版写回:ComfyUI 自己存的是紧凑的 JSON,只改了 `mosael` 那几处,别的字节一个不变(见 json_style)
    info = comfy.overwrite_userdata(f"workflows/{path}", json_style.dumps_like(updated, text))
    written = _seconds(info.get("modified"))
    return {"path": path, "modified": written if written is not None else _modified(comfy, path)}
