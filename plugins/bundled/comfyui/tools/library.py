"""模型库(ADR 0034):这台 ComfyUI 上有哪些模型文件 —— 列出、读元数据、推断底模家族、找哪几张工作流在用、缺哪些。

宿主按 `op` 问(见 main._generation):

    {"op": "library"}                         → 全部模型文件 + 各目录数目 + 工作流缺的模型 + 下载走哪条路
    {"op": "detail", "folder", "name"}        → 一个文件的完整元数据(文件头里的标量)与训练标签

用到的 ComfyUI 接口(0.38.0 实测,见 ADR 0034 的表):

- `/experiment/models`:每个模型目录在磁盘上的位置;`/experiment/models/{目录}`:文件名、目录序号、大小、改动时间;
- `/experiment/models/preview/{目录}/{序号}/{名字}`:预览图(没有就 404)—— 地址交给宿主,宿主去取、去缓存;
- 文件头:ComfyUI-Custom-Scripts 的 `/pysssss/view/{目录}/{名字}` 按段读(Range),只取开头 —— safetensors 的元数据和
  张量表、GGUF 的架构名和张量表,一个文件几十毫秒(见 model_files.HeaderRoute)。没装它的退回
  `/view_metadata/{目录}?filename=`:只有 safetensors 的 `__metadata__`,认不了权重结构。文本编码器目录里的文件同样读头,
  认的不是底模、是哪一种编码器(见 encoders)。

几百个文件第一次要读一阵:读到的东西按「服务器 + 目录 + 名字 + 大小 + 改动时间」记在持久目录里,第二次只读目录。记的是
**读到的原料**(认底模、触发词、标题要用的那几项元数据,权重认成的家族,GGUF 的架构名),家族每次列出时现推 —— 认的规矩
改了马上生效;权重那张表(weights.py)一改,缓存的版本对不上,整份扔掉重读。

同一个文件可能挂在几个目录下(ComfyUI-GGUF 的 `unet_gguf` 和 `diffusion_models` 指着同一批文件夹):按磁盘上的位置
只列一次(见 _deduplicated)。

老版本没有 `/experiment/models` 时退回 `/models/{目录}`:只有名字,没有大小和预览。
"""

from __future__ import annotations

import json
import posixpath
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib import parse

import civitai as civitai_mod
import convert
import encoders
import install
import models
import nsfw
import previews
import provenance
import weights
from families import family_applies, family_of, refined_by_civitai
from comfy_http import Comfy
from sources import canonical_url
from lines import ComfyError, say
from model_files import HEADER_SUFFIXES, SKIPPED_FOLDERS, HeaderRoute, data_file, files_in, folder_info, load_json, \
    metadata_of, save_json
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


def _top_tags(meta: dict[str, Any]) -> list[str]:
    """训练标签里出现最多的几个(一样多按字母)。"""
    counts = _tag_counts(meta)
    return [tag for tag, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:LIST_TRIGGERS]]


def triggers_of(meta: dict[str, Any], tags: list[str]) -> tuple[list[str], str]:
    """触发词:作者写在文件头里的(`modelspec.trigger_phrase` / `ss_trigger_words`)→ `metadata`;都没有时取训练标签里
    出现最多的几个(`tags`,见 _top_tags)→ `tags`(常见词,不一定是作者指定的触发词,界面上标明)。"""
    for key in ("modelspec.trigger_phrase", "ss_trigger_words"):
        raw = meta.get(key)
        if isinstance(raw, str) and raw.strip():
            return [one.strip() for one in raw.split(",") if one.strip()][:30], "metadata"
    return (tags[:LIST_TRIGGERS], "tags") if tags else ([], "")


def _title_of(meta: dict[str, Any]) -> str:
    for key in ("modelspec.title", "ss_output_name"):
        raw = meta.get(key)
        if isinstance(raw, str) and raw.strip():
            return raw.strip()[:200]
    return ""


def summarize(folder: str, name: str, inputs: dict[str, Any], origin: dict[str, Any] | None = None) -> dict[str, Any]:
    """一个文件读到的原料(见 _inputs;没读过的是空的,只按文件名认)和它的来源记录(见 provenance;没有是 None)→
    列表里那几格。每次列出都现推。"""
    meta = inputs.get("meta") or {}
    found = inputs.get("weights") or weights.family_of_gguf(inputs.get("gguf") or "")
    family, family_source = family_of(folder, name, meta, found)
    triggers, triggers_source = triggers_of(meta, list(inputs.get("tags") or []))
    title = _title_of(meta)
    civitai = (origin or {}).get("civitai") if isinstance((origin or {}).get("civitai"), dict) else None
    if civitai:
        family, family_source = refined_by_civitai(family, family_source, str(civitai.get("base_model") or ""))
    return {"family": family, "family_source": family_source, "encoder": encoders.describe(folder, name, inputs.get("encoder")),
            "triggers": triggers[:LIST_TRIGGERS],
            "triggers_source": triggers_source, "title": title,
            "nsfw_signals": nsfw.signals(name, title, dict(inputs.get("nsfw_tags") or {}), civitai),
            "source": source_of(origin, meta), "remote_previews": civitai_mod.remote_previews(civitai)}


def source_of(origin: dict[str, Any] | None, meta: dict[str, Any]) -> dict[str, str] | None:
    """这个文件的出处(原站上那一页):经 Mosael 下载时记下的、在 Civitai 上对上的(见 provenance);都没有时看文件自带的
    元数据,只认明说「来源 / 地址」的那几个键、指着一个模型页的。都没有就是 None —— 不按文件名猜一个链接。"""
    if origin and origin.get("page"):
        return {"page": str(origin["page"]), "site": str(origin.get("site") or ""), "how": str(origin.get("how") or "")}
    for key in _SOURCE_KEYS:
        value = str(meta.get(key) or "").strip()
        if any(pattern.match(value) for pattern in _MODEL_PAGES):
            site = "civitai" if "civitai" in value else "huggingface" if "huggingface" in value else "modelscope"
            return {"page": value.split()[0][:500], "site": site, "how": "metadata"}
    return None


# --- 持久目录里的记录:读到的原料 ------------------------------------------------

#: 元数据里能说明「这个文件就是原站上那一页」的键。描述、训练备注里的地址常指向作者主页、文章、底模仓库 —— 不算。
_SOURCE_KEYS = ("modelspec.source", "modelspec.url", "url", "source", "homepage", "Civitai url")
#: 原站上**一个模型的那一页**长什么样:Civitai 的模型页、HuggingFace 的仓库(不是数据集、空间)、ModelScope 的模型页。
_MODEL_PAGES = (
    re.compile(r"^https://(?:www\.)?civitai\.com/models/\d+"),
    re.compile(r"^https://huggingface\.co/(?!datasets/|spaces/|docs/|blog/)[\w.-]+/[\w.-]+"),
    re.compile(r"^https://(?:www\.)?modelscope\.(?:cn|ai)/models/[\w.-]+/[\w.-]+"),
)


#: 缓存的版本:格式,加上权重那张表、文本编码器那几张表的指纹 —— 表一改,记着的「认成了什么」就作废,整份重读。对不上就
#: 扔掉(缓存,不是用户的数据)。4:文本编码器目录里的文件也读头,记 `encoder`。
CACHE_VERSION = f"inputs-4:{weights.DIGEST}:{encoders.DIGEST}"
#: 元数据里留下的几项:认底模(families._declared / _narrowed)、触发词、标题要用的。别的在详情里现读。
_KEPT_META = ("ss_base_model_version", "modelspec.architecture", "ss_sd_model_name", "modelspec.title", "ss_v2",
              "ss_network_module", "ss_network_dim", "modelspec.trigger_phrase", "ss_trigger_words", "ss_output_name",
              *_SOURCE_KEYS)


def _inputs(meta: dict[str, Any], header: Any, folder: str = "") -> dict[str, Any]:
    """一个文件要记下的原料:`meta`(留下的那几项元数据)、`tags`(训练标签里最多的几个)、`nsfw_tags`(训练标签里的成人
    标签各占多少,见 nsfw.tag_shares)、`weights`(权重结构认成的家族,认不出是空串;**没有这一项**是还没读到文件头,下次
    有能用的读头地址时再读)、`gguf`(GGUF 的架构名)。文本编码器目录里的记 `encoder`(认成哪一种,规矩同 `weights`)。"""
    entry: dict[str, Any] = {"meta": {key: meta[key][:500] for key in _KEPT_META
                                      if isinstance(meta.get(key), str) and meta[key].strip()}}
    tags = _top_tags(meta)
    if tags:
        entry["tags"] = tags
    explicit = nsfw.tag_shares(_tag_counts(meta))
    if explicit:
        entry["nsfw_tags"] = explicit
    if header is not None:
        if encoders.applies(folder):
            entry["encoder"] = encoders.kind_of_header(header.tensors, header.architecture, header.sizes)
        else:
            entry["weights"] = weights.family_of_weights(header.tensors)
        if header.architecture:
            entry["gguf"] = header.architecture[:80]
    return entry


def _cache_key(folder: str, item: dict[str, Any]) -> str:
    return f"{folder}\n{item.get('name')}\n{item.get('size')}\n{item.get('modified')}"


def _reads_header(folder: str) -> bool:
    """这个目录的文件要不要读文件头认结构:讲底模的认家族,文本编码器认是哪一种;别的(放大、检测……)只要元数据。"""
    return family_applies(folder) or encoders.applies(folder)


def _readable(folder: str, name: str) -> bool:
    """有文件头可读的:safetensors 都读(元数据里有标题、触发词);GGUF 只在要认结构的目录里读(文本编码器的只读开头那一段
    键值,见 model_files.HeaderRoute)。"""
    lowered = name.lower()
    return lowered.endswith(HEADER_SUFFIXES) and (_reads_header(folder) or not lowered.endswith(".gguf"))


def _header_known(entry: dict[str, Any]) -> bool:
    """记着的原料里有没有文件头读出来的那一项(权重认成的家族 / 文本编码器的种类,认不出是空串也算读过)。"""
    return "weights" in entry or "encoder" in entry


# --- 同一个文件挂在几个目录下 ---------------------------------------------------

def _location(paths: list[str], item: dict[str, Any]) -> str | None:
    """文件在那台机器磁盘上的位置(比较用:斜杠统一、`.` 段去掉,Windows 路径不分大小写)。"""
    index = int(item.get("pathIndex") or 0)
    if index >= len(paths):
        return None
    base = paths[index]
    full = posixpath.normpath(f"{base}/{item['name']}".replace("\\", "/"))
    return full.lower() if re.match(r"^[A-Za-z]:/", full) else full


def _deduplicated(listing: dict[str, list[dict[str, Any]]], info: dict[str, list[str]]) -> dict[str, list[dict[str, Any]]]:
    """同一个文件只列一次。ComfyUI-GGUF 登记的 `unet_gguf` / `clip_gguf` 和 `diffusion_models` / `text_encoders` 指着同一批
    文件夹,Impact Pack 的 `ultralytics` 包着 `ultralytics_bbox` / `ultralytics_segm`:按磁盘上的位置认,留在先登记的那个
    目录(`/experiment/models` 的顺序:ComfyUI 自己的目录先登记,自定义节点的在后)。只有别名目录列着的照旧留在那儿。"""
    seen: set[str] = set()
    out: dict[str, list[dict[str, Any]]] = {}
    for folder, items in listing.items():
        kept: list[dict[str, Any]] = []
        for item in items:
            where = _location(info.get(folder) or [], item)
            if where is not None and where in seen:
                continue
            if where is not None:
                seen.add(where)
            kept.append(item)
        out[folder] = kept
    return out


# --- 工作流:在用哪些文件、声明了哪些下载地址 ---------------------------------

#: 一键下载只认这几个站:ComfyUI 官方前端缺模型时认的 HuggingFace、Civitai,加上 ModelScope 的两个站。工作流文件来自
#: 四面八方,不替陌生链接背书。地址先换成规范域名再比(见 sources.canonical_url)。
TRUSTED_SOURCES = ("https://huggingface.co/", "https://civitai.com/", "https://modelscope.cn/", "https://modelscope.ai/")


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


def _fed(api: dict[str, Any] | None, node: dict[str, Any], inner: bool) -> set[str] | None:
    """转出来的 API 图里,这个节点**实际**拿到的字符串;图里找不到它(没转、转不过来、不在会跑的那部分)是 None。

    子图里的节点在 API 图里是「子图节点 id:里层 id」(一个子图放了几次就有几份),按里层 id 和类型认,几份并起来。"""
    if not api or "class_type" in node:
        return None
    own, kind = str(node.get("id")), str(node.get("type") or "")
    found = [entry for key, entry in api.items() if isinstance(entry, dict) and entry.get("class_type") == kind
             and (key.rsplit(":", 1)[-1] == own if inner else key == own) and (":" in key) == inner]
    if not found:
        return None
    out: set[str] = set()
    for entry in found:
        out |= _strings(entry.get("inputs"))
    return out


def scan_workflow(ui_graph: dict[str, Any], api: dict[str, Any] | None = None) -> tuple[list[str], list[dict[str, str]]]:
    """一张图:(节点输入里写着的全部字符串, 真在用的那些下载声明)。

    下载声明是节点的 `properties.models`(官方模板的写法)和顶层的 `models`。只收**节点当前真在用**的:节点改选了别的
    文件,声明就过期了;顶层的声明要在某个节点的输入里写着。

    给了转出来的 API 图(`api`)时,「节点当前用的是哪个文件」以它为准:子图里的加载节点那一格接的是子图的输入口时,
    它自己存着的是模板默认值,真正用的是子图节点上提升出来的那一格 —— 维护者的 video_minimax_h3_t2v 在子图节点上
    换了 UNET,此前照里层存的旧值判「在用」,把一个没在用的十几 GB 的模型列成「缺的模型」、带着下载按钮。"""
    used: set[str] = set()
    declared: list[dict[str, str]] = []
    top = [one for one in ui_graph.get("nodes") or [] if isinstance(one, dict)] \
        if isinstance(ui_graph.get("nodes"), list) else []
    top_ids = {id(one) for one in top}
    for node in _nodes(ui_graph):
        values = _strings(node.get("widgets_values")) | _strings(node.get("inputs") if "class_type" in node else None)
        used |= values
        # 只有「widget 那一格接了线」的节点,它自己存着的值才不算数(值从线那头来:子图的输入口、Primitive……);别的节点
        # 照存着的判 —— 没装的节点转出来没有 widget 的值,不能拿 API 图里的空着当「没在用」
        linked = any(isinstance(entry, dict) and "widget" in entry and entry.get("link") is not None
                     for entry in node.get("inputs") or [] if "class_type" not in node)
        fed = _fed(api, node, inner=id(node) not in top_ids) if linked else None
        current = values if fed is None else fed
        for spec in (node.get("properties") or {}).get("models") or [] if isinstance(node.get("properties"), dict) else []:
            if isinstance(spec, dict) and _norm(str(spec.get("name") or "")) in current:
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


#: 「工作流里在用哪些文件、声明了哪些下载地址」那份记录的格式:判「在用」的规矩变了就换一个,旧的整份作废重扫。
#: 2:声明按转出来的 API 图判在不在用(子图里提升出来的那一格,见 scan_workflow)。
WORKFLOW_SCAN_VERSION = 2


def converted(ui_graph: dict[str, Any], object_info: dict[str, Any]) -> dict[str, Any] | None:
    """转成 API 图;转不过来(缺节点、坏文件)是 None —— 那就只能照节点上存着的判。"""
    try:
        return convert.to_api(ui_graph, object_info) if object_info else None
    except Exception:  # noqa: BLE001 — 转不过来不是错,退回老办法判
        return None


def _workflows(comfy: Comfy) -> list[tuple[str, str, list[str], list[dict[str, str]]]]:
    """每张保存的工作流:(id, 名字, 在用的字符串, 下载声明)。按「路径 + 大小 + 改动时间」记在持久目录里。

    要重扫的才去取节点定义(转 API 图要它),都记着的不取。"""
    cache_path = data_file(comfy, "workflow-models")
    saved = load_json(cache_path)
    cache = saved.get("files") if saved.get("version") == WORKFLOW_SCAN_VERSION and \
        isinstance(saved.get("files"), dict) else {}
    fresh: dict[str, Any] = {}
    out: list[tuple[str, str, list[str], list[dict[str, str]]]] = []
    listing = {str(item.get("path")): item for item in comfy.workflow_listing()}
    workflows, _others = comfy.saved_files()
    object_info: dict[str, Any] | None = None
    for path in workflows:
        item = listing.get(path) or {}
        key = f"{path}\n{item.get('size')}\n{item.get('modified')}"
        entry = cache.get(key)
        if not isinstance(entry, dict):
            try:
                source = comfy.fetch_workflow(path)
                if object_info is None:
                    object_info = comfy.object_info()
                used, declared = scan_workflow(source, converted(source, object_info))
            except ComfyError:
                continue
            entry = {"used": used, "declared": declared}
        fresh[key] = entry
        out.append((path, models.label_of(path), list(entry.get("used") or []), list(entry.get("declared") or [])))
    if fresh != cache or saved.get("version") != WORKFLOW_SCAN_VERSION:
        save_json(cache_path, {"version": WORKFLOW_SCAN_VERSION, "files": fresh})
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
    shown = listing if info is None else _deduplicated(listing, info)

    cache_path = data_file(comfy, "library")
    saved = load_json(cache_path)
    files = saved.get("files") if saved.get("version") == CACHE_VERSION else None
    cache: dict[str, Any] = files if isinstance(files, dict) else {}
    fresh: dict[str, Any] = {}
    route = HeaderRoute(comfy)
    wanted = [(folder, item, cache.get(_cache_key(folder, item))) for folder, items in shown.items() for item in items
              if _readable(folder, str(item.get("name")))]
    # 没读过的;读过、但当时没有能用的读头地址(没装 ComfyUI-Custom-Scripts)的再试一次 —— 这一趟还是没有,第一个文件
    # 试过就不再试
    wanted = [job for job in wanted
              if job[2] is None or (not _header_known(job[2]) and _reads_header(job[0]))]

    def read(job: tuple[str, dict[str, Any], dict[str, Any] | None]) -> tuple[str, dict[str, Any]]:
        folder, item, old = job
        name = str(item["name"])
        key = _cache_key(folder, item)
        header = route.read(folder, name, tensors=not encoders.applies(folder)) if _reads_header(folder) else None
        if header is not None:
            meta = header.meta if header.meta is not None else metadata_of(comfy, folder, name)
            return key, _inputs(meta or {}, header, folder)
        if old is not None:
            return key, old  # 元数据上次读过了;权重等有了读头的地址再认
        return key, _inputs(metadata_of(comfy, folder, name) or {}, None)

    # 第一个要读头的先单独读:顺便看清这台有没有能用的读头地址 —— 没有的话,别让几个线程一起去撞
    first = next((job for job in wanted if _reads_header(job[0])), None)
    if first is not None:
        fresh.update([read(first)])
    rest = [job for job in wanted if job is not first]
    if rest:
        with ThreadPoolExecutor(max_workers=METADATA_WORKERS) as pool:
            fresh.update(dict(pool.map(read, rest)))

    workflows = _workflows(comfy)
    used_by: dict[str, list[dict[str, str]]] = {}
    for ident, label, used, _declared in workflows:
        for value in used:
            used_by.setdefault(value, []).append({"id": ident, "label": label})

    origins = provenance.load(comfy)
    out_models: list[dict[str, Any]] = []
    for folder, items in shown.items():
        for item in items:
            name = str(item["name"])
            key = _cache_key(folder, item)
            inputs = fresh.get(key) or cache.get(key)
            if inputs is not None:
                fresh[key] = inputs
            origin = provenance.find(origins, folder, name, item.get("size"))
            summary = summarize(folder, name, inputs or {}, origin)  # 没有文件头的(.ckpt、.pt……)只按文件名认
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
    if fresh != cache or saved.get("version") != CACHE_VERSION:
        save_json(cache_path, {"version": CACHE_VERSION, "files": fresh})

    # 「在不在」按 ComfyUI 自己的列法:别名目录里那一份也算(工作流里的 UnetLoaderGGUF 按 unet_gguf 找)
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

    ways = previews.tools(comfy)
    out: dict[str, Any] = {
        "folders": [{"name": folder, "count": len(items)} for folder, items in shown.items()],
        "models": out_models,
        "missing": list(missing.values()),
        "download": install.describe(comfy, info, listing, locale),
        # 找预览图、写回预览图走哪条路(见 previews):按哈希找要 ComfyUI-Custom-Scripts,没有它只能按文件名找
        "preview_tools": {"lookup": "sha256" if ways["hash"] else "filename", "save": ways["save"],
                          "save_note": "" if ways["save"] else previews.missing_tool(locale)},
    }
    if info is not None and ways["save"]:
        # 模型旁边的预览视频、文件名带 [ ] 的那几张图:按名字直接读(和 /pysssss/save 同一个模块的 /pysssss/view)
        out["sidecar_base"] = f"{comfy.base}/pysssss/view/"
        # 预览图的原文件(本机识别看它,不看 ComfyUI 转出来的有损 WebP):一个目录问一次
        originals = previews.originals(comfy, sorted({entry["folder"] for entry in out_models}))
        for entry in out_models:
            entry["sidecars"] = previews.sidecars(entry["folder"], entry["name"])
            original = originals.get((entry["folder"], entry["name"].replace("\\", "/")))
            if original:
                entry["preview_file"] = original
    if info is not None:
        out["preview_base"] = f"{comfy.base}/experiment/models/preview/"
        if comfy.headers:
            out["preview_headers"] = dict(comfy.headers)
    return _within_budget(out, locale)


def _within_budget(out: dict[str, Any], locale: str) -> dict[str, Any]:
    """一次回答最多 1 MB。几千个文件时先削触发词、「在用的工作流」、标题,还不够就只列前面的,并说一句。"""
    def size() -> int:
        return len(json.dumps(out, ensure_ascii=False).encode("utf-8"))

    for trim in ("preview_file", "triggers", "used_by", "title", "sidecars"):
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
    return {"folder": folder, "name": name, "metadata": shown, "tags": tags}
