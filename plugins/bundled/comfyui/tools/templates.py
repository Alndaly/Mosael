"""ComfyUI 的模板(ADR 0042 §3):「我想要一个 X 的工作流」先落到官方调好的图上,而不是让模型现编一张。

    {"op": "templates", "query"?, "task"?, "model"?, "limit"?} → 按任务、模型、关键词找;每条带它要的模型(这台机器上有哪几个、
                                                                有同款的另一种精度、缺哪几个)、模型合计多大、要哪一版 ComfyUI
    {"op": "template", "name", "pack"?}                        → 一张的整图,照这台机器改好能改的,说改了什么;还缺什么、多大

模板从哪来(都是那台 ComfyUI 自己提供的,ComfyUI 0.39 / 模板包 0.11.76 核对过):

- 官方模板随 ComfyUI 装(pip 包 `comfyui_workflow_templates*`):`/templates/index.mcp.json`(给智能体读的那一份:任务、模型、
  新旧、推荐程度、输入输出一句话、最低版本)、`/templates/index.json`(模型合计大小 `size`、`tags`、`models`)、界面语言那一份
  `/templates/index.<语言>.json`(标题、说明、标签的译文),每一张是 `/templates/<名字>.json`(界面格式,能直接载进画布)。
- 节点包自带的模板:`/workflow_templates`(包 → 模板名)、文件在 `/api/workflow_templates/<包>/<名字>.json`。

**这台机器上有没有**:模板的每个节点上声明了要的模型(`properties.models`:文件名、目录、下载地址)。对着模型库的那份数据看
(那个目录里的文件,model_files.names_in);`template` 再对着加载节点自己的下拉(那一类节点的定义,node_catalog.classes)。

**照这台机器改**(`template`),只改两种,都说出来,**从不编一个文件名**:

1. 同一个文件在那个加载节点能读的另一个子目录里(`qwen/xxx.safetensors`)—— 改成那个路径;
2. 同一个模型的另一种精度 / 量化(去掉 fp8、bf16、int8、gguf、Q4_K_M 这类标记以后名字一样)—— 改成这台机器上有的那一个。

别的缺着就缺着:说缺哪几个、去哪下、多大(问那个下载地址,HuggingFace 回的 `x-linked-size`)。
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from urllib import parse

import canvas
import convert
import labels
import node_catalog
import sources
from comfy_http import Comfy
from lines import ComfyError, say
from model_files import data_file, load_json, names_in, norm, save_json
from workflow_library import _choices

#: 一次最多回几张(每张都要取一遍它的整图看要哪些模型)。
MAX_RESULTS = 12
DEFAULT_RESULTS = 6
#: 同时取几张模板 / 问几个下载地址。
WORKERS = 6
#: 模板名、节点包名长什么样(拼进地址里,不收斜杠和 `..`)。
_NAME = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.\- ()+]{0,199}$")
#: 精度 / 量化的标记:去掉它们以后名字一样的,是同一个模型的另一种存法。
_PRECISION = re.compile(
    r"^(?:fp\d+|bf16|int\d+|nf4|e\d+m\d+(?:fn)?|scaled|convrot|pruned|gguf|q\d+(?:_[0k])?(?:_[a-z])?|"
    r"mxfp\d+|svdq|fp8mixed|mixed|distilled_fp8)$")
_RECOMMEND = {"highly_recommended": 3, "recommended": 2, "standard": 1}
_FRESHNESS = {"new": 2, "established": 1}


# --- 索引 --------------------------------------------------------------------------

def _get_json(comfy: Comfy, path: str) -> Any:
    try:
        return comfy.get(path)
    except ComfyError as exc:
        if exc.status == 404:
            return None
        raise


def _flat(index: Any) -> dict[str, dict[str, Any]]:
    """`[{category, templates: [...]}, …]` → 名字 → 那一张(带上它所在的类别)。"""
    found: dict[str, dict[str, Any]] = {}
    for category in index if isinstance(index, list) else []:
        if not isinstance(category, dict):
            continue
        for one in category.get("templates") or []:
            if isinstance(one, dict) and isinstance(one.get("name"), str) and one["name"] not in found:
                found[one["name"]] = {**one, "_category": str(category.get("title") or category.get("category") or "")}
    return found


def _language(locale: str) -> str:
    """界面语言对应哪一份译文:`zh`(简体)那一份叫 index.zh.json;英文就是 index.json 本身。"""
    lowered = (locale or "").lower()
    return "zh" if lowered.startswith("zh") else ""


def templates_version(comfy: Comfy) -> str:
    """装着的模板包是哪一版(`/system_stats` 的 installed_templates_version,0.3x 起有);说不出是空串。"""
    try:
        return str((comfy.system_stats().get("system") or {}).get("installed_templates_version") or "")
    except ComfyError:
        return ""


def load_index(comfy: Comfy, locale: str) -> dict[str, dict[str, Any]]:
    """三份索引合成一份(见 _merged)。按模板包的版本记在持久目录里:三份合起来两 MB 左右,慢的局域网上要传好几秒,而它们
    只在模板包升级时才变。"""
    version = templates_version(comfy)
    language = _language(locale)
    path = data_file(comfy, "templates-index")
    saved = load_json(path)
    if version and saved.get("version") == version and saved.get("language") == language and isinstance(saved.get("index"), dict):
        return saved["index"]
    merged = _merged(comfy, language)
    if version and merged:
        save_json(path, {"version": version, "language": language, "index": merged})
    return merged


def _merged(comfy: Comfy, language: str) -> dict[str, dict[str, Any]]:
    """名字 → mcp 那一份的字段 + index.json 的 size / tags / models + 译文的 title_l10n / description_l10n。"""
    mcp = _flat(_get_json(comfy, "/templates/index.mcp.json"))
    full = _flat(_get_json(comfy, "/templates/index.json"))
    local = _flat(_get_json(comfy, f"/templates/index.{language}.json")) if language else {}
    merged: dict[str, dict[str, Any]] = {}
    for name in [*mcp, *(one for one in full if one not in mcp)]:
        base = full.get(name, {})
        entry = {**base, **mcp.get(name, {})}
        translated = local.get(name, {})
        if translated.get("title"):
            entry["title_l10n"] = translated["title"]
        if translated.get("description"):
            entry["description_l10n"] = translated["description"]
        if isinstance(translated.get("tags"), list):
            entry["tags_l10n"] = translated["tags"]
        for key in ("size", "tags", "models", "mediaType", "date"):
            if key in base:
                entry[key] = base[key]
        merged[name] = entry
    return merged


def comfy_version(comfy: Comfy) -> str:
    try:
        return str((comfy.system_stats().get("system") or {}).get("comfyui_version") or "")
    except ComfyError:
        return ""


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(part) for part in re.findall(r"\d+", text or "")[:4])


def version_ok(minimum: str, current: str) -> bool | None:
    """这台的版本够不够;两头有一头说不清就是 None。"""
    if not minimum or not current:
        return None
    return _version_tuple(current) >= _version_tuple(minimum)


# --- 找 ------------------------------------------------------------------------------

def _haystack(entry: dict[str, Any]) -> dict[str, str]:
    def joined(*keys: str) -> str:
        parts: list[str] = []
        for key in keys:
            value = entry.get(key)
            if isinstance(value, list):
                parts += [str(one) for one in value]
            elif isinstance(value, dict):
                parts += [str(one) for values in value.values() if isinstance(values, list) for one in values]
            elif value:
                parts.append(str(value))
        return " ".join(parts).lower()

    return {
        "title": joined("title", "title_l10n", "name"),
        "model": joined("model", "models"),
        "task": joined("task", "tags", "tags_l10n", "capabilities", "_category"),
        "text": joined("description", "description_l10n"),
    }


def _score(entry: dict[str, Any], terms: list[str], task: str, model: str) -> int:
    hay = _haystack(entry)
    if task and task not in hay["task"] and task not in hay["title"]:
        return 0
    if model and model not in hay["model"] and model not in hay["title"]:
        return 0
    score = 1 if (task or model) else 0
    for term in terms:
        if term in hay["title"]:
            score += 12
        elif term in hay["model"]:
            score += 10
        elif term in hay["task"]:
            score += 6
        elif term in hay["text"]:
            score += 2
        else:
            return 0
    return score


def _terms(text: str) -> list[str]:
    return [one for one in re.split(r"[\s,,;;/]+", (text or "").lower()) if one]


def _rank(index: dict[str, dict[str, Any]], query: str, task: str, model: str) -> list[str]:
    terms = _terms(query)
    task, model = task.strip().lower(), model.strip().lower()
    scored = [(score, name) for name, entry in index.items() if (score := _score(entry, terms, task, model)) > 0]

    def tie(name: str) -> tuple[int, int, int]:
        entry = index[name]
        return (_RECOMMEND.get(str(entry.get("recommend") or ""), 0), _FRESHNESS.get(str(entry.get("freshness") or ""), 0),
                int(entry.get("usage") or 0) if isinstance(entry.get("usage"), int) else 0)

    return [name for _, name in sorted(scored, key=lambda one: (-one[0], *(-value for value in tie(one[1])), one[1]))]


# --- 一张模板要哪些模型 -----------------------------------------------------------

def fetch(comfy: Comfy, name: str, pack: str, locale: str) -> dict[str, Any]:
    """一张模板的界面格式整图。"""
    if not _NAME.match(name or "") or (pack and not _NAME.match(pack)):
        raise ComfyError(say(locale, f"「{name}」不是一个模板名", f"“{name}” is not a template name"))
    path = (f"/api/workflow_templates/{parse.quote(pack, safe='')}/{parse.quote(name, safe='')}.json" if pack
            else f"/templates/{parse.quote(name, safe='')}.json")
    found = _get_json(comfy, path)
    if not isinstance(found, dict) or not isinstance(found.get("nodes"), list):
        raise ComfyError(say(locale, f"这台 ComfyUI 上没有模板「{name}」", f"This ComfyUI has no template “{name}”"))
    return found


def declared_models(content: dict[str, Any]) -> list[dict[str, str]]:
    """节点上声明的模型(`properties.models`):文件名、目录、下载地址;同一个文件只列一次。"""
    found: dict[tuple[str, str], dict[str, str]] = {}
    for scope in [content, *canvas.definitions(content).values()]:
        for node in canvas.nodes_of(scope):
            for one in ((node.get("properties") or {}).get("models") or []):
                if isinstance(one, dict) and isinstance(one.get("name"), str) and one["name"].strip():
                    key = (str(one.get("directory") or ""), norm(one["name"]))
                    found.setdefault(key, {"name": norm(one["name"]), "folder": key[0], "url": str(one.get("url") or "")})
    return list(found.values())


def _where(name: str, files: set[str]) -> str:
    """这个文件在这台机器那个目录里叫什么:原样在就是原样,换了个子目录就是那个路径,没有是空串。"""
    if name in files:
        return name
    base = name.split("/")[-1]
    return next((one for one in sorted(files) if one.split("/")[-1] == base), "")


def model_status(comfy: Comfy, models: list[dict[str, str]], cache: dict[str, set[str]]) -> list[dict[str, Any]]:
    """每个要的模型这台机器上有没有(对着模型库那份数据:那个目录里的文件)。"""
    out: list[dict[str, Any]] = []
    for one in models:
        folder = one["folder"]
        if folder and folder not in cache:
            try:
                cache[folder] = names_in(comfy, folder)
            except ComfyError:
                cache[folder] = set()
        files = cache.get(folder, set())
        where = _where(one["name"], files) if folder else ""
        entry: dict[str, Any] = {"name": one["name"], "folder": folder, "present": bool(where)}
        if where and where != one["name"]:
            entry["found_as"] = where
        if not where:
            alternatives = sorted(name for name in files if _stem(name) == _stem(one["name"]))
            if alternatives:
                entry["alternative"] = alternatives[0]
            elif one["url"]:
                entry["url"] = one["url"]
        out.append(entry)
    return out


def _result(name: str, entry: dict[str, Any], current: str) -> dict[str, Any]:
    out: dict[str, Any] = {
        "name": name,
        "title": str(entry.get("title_l10n") or entry.get("title") or name),
        "task": str(entry.get("task") or ""),
        "model": str(entry.get("model") or "") or ", ".join(str(one) for one in entry.get("models") or []),
        "description": str(entry.get("description_l10n") or entry.get("description") or "")[:400],
    }
    if entry.get("title_l10n") and entry.get("title"):
        out["title_en"] = str(entry["title"])
    minimum = str(entry.get("minComfyUIVersion") or "")
    if minimum:
        out["min_comfyui"] = minimum
        out["version_ok"] = version_ok(minimum, current)
    for key in ("freshness", "recommend", "usage"):
        if entry.get(key):
            out[key] = entry[key]
    if isinstance(entry.get("size"), (int, float)) and entry["size"] > 0:
        out["size"] = int(entry["size"])
    io = entry.get("io")
    if isinstance(io, dict) and all(isinstance(value, list) and all(isinstance(one, str) for one in value) for value in io.values()):
        out["io"] = io
    return out


def templates(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    query = str(payload.get("query") or "")
    task = str(payload.get("task") or "")
    model = str(payload.get("model") or "")
    if not (query.strip() or task.strip() or model.strip()):
        raise ComfyError(say(locale, "说说要做什么(任务、模型或关键词)", "Say what you want to make (a task, a model or keywords)"))
    limit = payload.get("limit")
    limit = max(1, min(MAX_RESULTS, limit)) if isinstance(limit, int) and not isinstance(limit, bool) else DEFAULT_RESULTS
    index = load_index(comfy, locale)
    current = comfy_version(comfy)
    ranked = _rank(index, query, task, model)
    picked = ranked[:limit]
    graphs: dict[str, dict[str, Any] | None] = {}

    def load(name: str) -> tuple[str, dict[str, Any] | None]:
        try:
            return name, fetch(comfy, name, "", locale)
        except ComfyError:
            return name, None

    if picked:
        with ThreadPoolExecutor(max_workers=min(WORKERS, len(picked))) as pool:
            graphs = dict(pool.map(load, picked))
    cache: dict[str, set[str]] = {}
    results: list[dict[str, Any]] = []
    for name in picked:
        out = _result(name, index[name], current)
        content = graphs.get(name)
        if content is not None:
            status = model_status(comfy, declared_models(content), cache)
            out["models"] = status
            #: 缺的:这台机器上连同款的另一种精度都没有(有同款的 `template` 会换成它)
            out["missing"] = [one["name"] for one in status if not one["present"] and not one.get("alternative")]
        results.append(out)
    packs = _pack_templates(comfy, query or task or model)
    return {"templates": results, "matched": len(ranked), "total": len(index), "comfyui_version": current,
            "pack_templates": packs}


def _pack_templates(comfy: Comfy, query: str) -> list[dict[str, str]]:
    """节点包自带的模板里名字对得上的(它们没有索引,只有包名和模板名)。"""
    listed = _get_json(comfy, "/workflow_templates")
    terms = _terms(query)
    found: list[dict[str, str]] = []
    for pack, names in (listed.items() if isinstance(listed, dict) else []):
        for name in names if isinstance(names, list) else []:
            text = f"{pack} {name}".lower().replace("_", " ").replace("-", " ")
            if terms and all(term in text or term in f"{pack} {name}".lower() for term in terms):
                found.append({"pack": str(pack), "name": str(name)})
    return found[:10]


# --- 一张模板,照这台机器改好 -------------------------------------------------------

def _stem(name: str) -> str:
    """去掉目录、扩展名和精度 / 量化标记以后的名字(`qwen_image_2.1_int8_convrot.safetensors` → `qwen image 2 1`)。"""
    base = norm(name).split("/")[-1].lower()
    base = re.sub(r"\.(safetensors|sft|ckpt|pt|pth|bin|gguf)$", "", base)
    words = [one for one in re.split(r"[-_.\s]+", base) if one and not _PRECISION.match(one)]
    return " ".join(words)


def _replace(content: dict[str, Any], old: str, new: str, *, forget_download: bool) -> int:
    """把图里(各层的节点,连同子图节点上提升出来的值)写着 `old` 的控件值换成 `new`。回换了几处。

    `forget_download`:换成了另一个文件(另一种精度)时,节点上为 `old` 声明的下载(文件名 + 地址)去掉 —— 留着的话,前端的
    「缺失的模型」会照那个地址去下一个这张图已经不用的文件。只是换了子目录时声明照旧(说的还是同一个文件)。"""
    count = 0

    def same(value: Any) -> bool:
        return isinstance(value, str) and norm(value) == norm(old)

    for scope in [content, *canvas.definitions(content).values()]:
        for node in canvas.nodes_of(scope):
            values = node.get("widgets_values")
            if isinstance(values, list):
                for index, value in enumerate(values):
                    if same(value):
                        values[index] = new
                        count += 1
            elif isinstance(values, dict):
                for key, value in list(values.items()):
                    if same(value):
                        values[key] = new
                        count += 1
            declared = (node.get("properties") or {}).get("models")
            if forget_download and isinstance(declared, list):
                kept = [one for one in declared if not (isinstance(one, dict) and isinstance(one.get("name"), str)
                                                        and norm(one["name"]).split("/")[-1] == norm(old).split("/")[-1])]
                if len(kept) != len(declared):
                    node["properties"]["models"] = kept
    return count


def _model_inputs(content: dict[str, Any], object_info: dict[str, Any], locale: str) -> list[tuple[str, str, str, list[str]]]:
    """真会跑的那张图里每一格选模型文件的:(值, 节点类型, 输入名, 那个加载节点能选的文件)。"""
    try:
        api = convert.to_api(content, object_info, locale)
    except ComfyError:
        return []
    found: list[tuple[str, str, str, list[str]]] = []
    seen: set[tuple[str, str, str]] = set()
    for node in api.values():
        kind = str(node.get("class_type") or "")
        spec = object_info.get(kind) or {}
        declared = spec.get("input") if isinstance(spec.get("input"), dict) else {}
        defs = {**(declared.get("optional") or {}), **(declared.get("required") or {})}
        for name, value in (node.get("inputs") or {}).items():
            if not isinstance(value, str) or not (labels.model_folder(kind, name) or value.lower().endswith(
                    (".safetensors", ".sft", ".ckpt", ".pt", ".pth", ".bin", ".gguf"))):
                continue
            choices = _choices(defs.get(name))
            if choices is None or (kind, name, value) in seen:
                continue
            seen.add((kind, name, value))
            found.append((value, kind, name, [norm(str(one)) for one in choices if isinstance(one, str)]))
    return found


def _sizes(urls: list[str]) -> dict[str, int]:
    """下载地址 → 多大(问一下,不下载;HuggingFace 第一跳就给 x-linked-size)。问不到的不在结果里。"""
    def ask(url: str) -> tuple[str, int | None]:
        try:
            answer = sources.follow(url)
        except Exception:  # noqa: BLE001 — 只是一个参考数字,问不到就不写
            return url, None
        raw = answer.headers.get("x-linked-size") or answer.headers.get("content-length") or ""
        return url, int(raw) if str(raw).isdigit() and answer.status < 400 else None

    wanted = [one for one in dict.fromkeys(urls) if one.startswith("https://")]
    if not wanted:
        return {}
    with ThreadPoolExecutor(max_workers=min(WORKERS, len(wanted))) as pool:
        return {url: size for url, size in pool.map(ask, wanted) if size}


def adapt(content: dict[str, Any], object_info: dict[str, Any], locale: str) -> tuple[list[dict[str, Any]], list[str]]:
    """照这台机器改(就地改 `content`):每个要的模型现在什么样,和改了什么(给人看的话)。"""
    declared = {item["name"].split("/")[-1]: item for item in declared_models(content)}
    models: list[dict[str, Any]] = []
    changes: list[str] = []
    for value, kind, name, choices in _model_inputs(content, object_info, locale):
        base = norm(value).split("/")[-1]
        info = declared.get(base, {})
        entry: dict[str, Any] = {"name": norm(value), "folder": labels.model_folder(kind, name) or info.get("folder", ""),
                                 "node_type": kind, "input": name}
        if norm(value) in choices:
            entry["status"] = "present"
        elif (elsewhere := next((one for one in choices if one.split("/")[-1] == base), "")):
            _replace(content, value, elsewhere, forget_download=False)
            entry.update(status="adapted", use=elsewhere)
            changes.append(str(say(locale, f"「{value}」这台机器上在「{elsewhere}」,改成了它",
                                   f"“{value}” is at “{elsewhere}” on this machine; switched to it")))
        elif (alternatives := sorted(one for one in choices if _stem(one) == _stem(value) and one != norm(value))):
            _replace(content, value, alternatives[0], forget_download=True)
            entry.update(status="adapted", use=alternatives[0])
            others = f"(还有 {len(alternatives) - 1} 个同款)" if len(alternatives) > 1 else ""
            changes.append(str(say(locale, f"「{value}」换成了这台机器上同一个模型的另一种精度 / 量化「{alternatives[0]}」{others}",
                                   f"Swapped “{value}” for “{alternatives[0]}”, another precision / quantisation of the same model on this machine")))
        else:
            entry["status"] = "missing"
            if info.get("url"):
                entry["url"] = info["url"]
        models.append(entry)
    return models, changes


def template(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    name = str(payload.get("name") or "").strip()
    pack = str(payload.get("pack") or "").strip()
    content = fetch(comfy, name, pack, locale)
    object_info = node_catalog.classes(comfy, canvas.class_types(content))
    models, changes = adapt(content, object_info, locale)
    sizes = _sizes([one["url"] for one in models if one["status"] == "missing" and one.get("url")])
    for one in models:
        if one.get("url") in sizes:
            one["size"] = sizes[one["url"]]
    out: dict[str, Any] = {"name": name, "models": models, "changes": changes,
                           "missing_size": sum(one.get("size", 0) for one in models if one["status"] == "missing")}
    if pack:
        out["pack"] = pack
    else:
        entry = load_index(comfy, locale).get(name, {})
        out.update({key: value for key, value in _result(name, entry, comfy_version(comfy)).items() if key != "name"})
    summary = canvas.summarize(content, object_info)
    out["missing_types"] = summary["missing_types"]
    out["summary"] = summary
    out["workflow"] = content
    if len(json.dumps(out, ensure_ascii=False)) > 900_000:
        out.pop("summary")
    return out


__all__ = ["adapt", "declared_models", "fetch", "load_index", "template", "templates", "version_ok"]
