"""按文件名找一个模型的下载地址:去 HuggingFace、ModelScope、Civitai 上搜(工作台「缺失项」里的「找下载地址」)。

    {"op": "search_sources", "filename": "…", "folder": "…"} → {"filename", "candidates": […], "failed": […]}

工作流里只写了文件名、没写下载地址的模型,原来要用户自己去三个站上一个个搜。这里替他搜,每个站依次用三个词:

1. 完整文件名(去掉目录前缀:`sub\\x.safetensors` 搜 `x.safetensors`);
2. 去掉扩展名的名字(stem);
3. stem 再去掉末尾的精度 / 量化后缀(`_fp8`、`-fp16`、`_bf16`、`_e4m3fn`、`_scaled`、`-Q4_K_M`……,见 PRECISION)——
   同一个模型常有好几种精度,工作流要的那种没有时,别的精度也值得列出来。

一个站找到同名文件就不再往下搜那个站。**同名**(`exact`)是文件名一样(不分大小写,只比最后一段);别的都是**近似**:
stem 一样只是扩展名不同、去掉精度后缀之后一样,或者文件名里含着那个去掉后缀的名字。近似的永远不标 `exact`。

**排序**:同名的在前;同名里按 `folder`(要放进的模型目录,给了的话)对得上的在前,再按站(HuggingFace、ModelScope、
Civitai),同一个站里按站点给的先后(热度 / 相关度)。近似的在后:「stem 一样 / 去掉后缀一样」比「只是含着」靠前,
同一档里同样先看目录再看站,同一个站里按大小(小的在前,不知道大小的最后)。最多 20 个,一个站最多 8 个。

**每个候选的 `url` 都是 `resolve`(见 sources)认得、并且正好解析到这个文件的链接** —— 界面点了候选就拿它去 resolve,
再走下载那一步:

- HuggingFace:`https://huggingface.co/{仓库}/resolve/main/{路径}`;
- ModelScope:`https://modelscope.cn/models/{仓库}/resolve/master/{路径}`(和 resolve 交回的直链同一个形状);
- Civitai:`https://civitai.com/api/download/models/{版本}`(主文件)或 `…?type={类型}`。resolve 只看下载链接里的
  `type`:带了就取那一类里排第一的文件,没带就取主文件(见 sources._civitai)。所以一个版本里只有主文件和「那一类里
  排第一的」钉得住;同一版本里同类的别的文件(同一个模型的 fp32、.ckpt 那几份)钉不住 —— 列出来点了会解析成另一个
  文件,所以**不列**(见 `_civitai_pinned`)。

**一个站出了问题不拖累别的站**:三个站并行地搜,一个站超时、限流、拒绝,只把它记进 `failed`(一句给人看的话),
别的站照常交回。去这些站走 sources 的同一个出网口(宿主给这个连接的出站、插件自己的 User-Agent),**不带令牌** ——
公开的搜索接口不用登录。

**HuggingFace 的搜索只比仓库名,不比文件名**:ComfyUI 官方模板用的文件大都在 Comfy-Org 名下的仓库里(按 ComfyUI 的
目录名拆好的那些),仓库名里却没有文件名。所以先把 Comfy-Org 的全部仓库连同文件列表拉一次(一个请求)对一遍,
再按词搜。搜到的仓库只交文件名,大小另问:最多问 4 个仓库(`?blobs=true`),问不到就不写大小。

**ModelScope** 用的是它不要令牌的公开接口 `/openapi/v1/models?search=`(只交仓库,不交文件),每个词最多再看 4 个
仓库的文件列表(和 sources 读文件列表同一个接口)。只搜 modelscope.cn,不搜国际站 modelscope.ai。

**记一会儿**:插件每次调用是一个新进程,内存里记不住 —— 记在插件持久目录的 `model-search.json` 里(没有持久目录就
不记)。搜索结果、文件列表记 10 分钟,Comfy-Org 的仓库清单记 6 小时;失败的不记。记的是解析后剪过的那几项,不是
原始回答。
"""

from __future__ import annotations

import http.client
import json
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib import parse

import sources
from comfy_http import Comfy
from lines import ComfyError, say
from model_files import load_json, save_json

#: 同样贴近时的站点次序。
SITES = ("huggingface", "modelscope", "civitai")
#: 一次最多交回几个候选,一个站最多占几个。
MAX_CANDIDATES = 20
PER_SITE = 8
#: 一个请求最多等几秒。
TIMEOUT = 12
#: 每个搜索接口一次要几条(仓库 / 模型)。
SEARCH_LIMIT = 10
#: HuggingFace 最多问几个仓库的文件大小;ModelScope 每个词最多看几个仓库的文件列表。
HF_SIZE_LOOKUPS = 4
MS_FILE_LOOKUPS = 4
#: 记多久(秒):搜索结果和文件列表、Comfy-Org 的仓库清单。
SEARCH_TTL = 600
CATALOG_TTL = 6 * 3600
#: 记在插件持久目录里的哪个文件、最多记几条。
CACHE_FILE = "model-search.json"
CACHE_VERSION = 1
MAX_CACHE_ENTRIES = 200
#: 文件名末尾的精度 / 量化后缀(一段一段地去掉,`_fp8_e4m3fn_scaled` 三段都去)。
PRECISION = re.compile(
    r"[-_.](?:fp8|fp16|fp32|bf16|f16|f32|fp4|nvfp4|mxfp4|e4m3fn|e5m2|int8|int4|scaled|q\d+(?:_[a-z0-9]+)*)$",
    re.IGNORECASE,
)
#: HuggingFace 上 Comfy-Org 名下的全部仓库,连同文件列表。
HF_CATALOG = "https://huggingface.co/api/models?" + parse.urlencode({"author": "Comfy-Org", "full": "true", "limit": 1000})

Json = Any


def _basename(name: str) -> str:
    return re.split(r"[\\/]", name.strip())[-1].strip()


def _stem(name: str) -> str:
    stem, dot, _ = name.rpartition(".")
    return stem if dot and stem else name


def _core(stem: str) -> str:
    """去掉末尾的精度 / 量化后缀。去完不剩什么(整个名字就是 `fp16` 这种)就不去。"""
    core = stem
    while True:
        shorter = PRECISION.sub("", core)
        if shorter == core or len(shorter) < 3:
            return core
        core = shorter


class _Target:
    """要找的那个文件:文件名、stem、去掉后缀的 stem,以及依次要搜的词。"""

    def __init__(self, filename: str) -> None:
        self.filename = filename
        self.lower = filename.lower()
        stem = _stem(filename)
        core = _core(stem)
        self.stem, self.core = stem.lower(), core.lower()
        self.queries = list(dict.fromkeys(one for one in (filename, stem, core) if one))
        #: Civitai 把上传的文件改名成「模型名_版本名」(驼峰):它的搜索只比模型名里的词,`realisticVisionV60B1_v51VAE`
        #: 搜不到,`realistic Vision V60B1` 搜得到。所以 Civitai 多搜一个词:第一个 `_` 之前那段,按驼峰拆开。
        first = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem.split("_")[0]).strip()
        self.words = first if len(first) >= 3 and first not in self.queries else ""

    def tier(self, name: str) -> int | None:
        """0:同名;1:stem 一样或去掉精度后缀之后一样;2:文件名里含着去掉后缀的名字;对不上是 None。
        近似的只认模型文件(.safetensors、.gguf……),同名的不论扩展名。"""
        base = _basename(name).lower()
        if base == self.lower:
            return 0
        if not base.endswith(sources.MODEL_EXTENSIONS):
            return None
        stem = _stem(base)
        if stem == self.stem or _core(stem) == self.core:
            return 1
        if len(self.core) >= 4 and self.core in stem:
            return 2
        return None


@dataclass
class Candidate:
    source: str
    repo: str
    title: str
    filename: str
    url: str
    page: str
    size: int | None
    base_model: str
    tier: int
    #: 仓库里的路径(HuggingFace 补大小时按它对)。
    path: str = ""
    #: 这个文件在哪些目录名下(HuggingFace / ModelScope 是路径里的那几段,Civitai 是按模型类型推的目录)。排序时和
    #: 请求里的 `folder` 比,不交出去。
    folders: tuple[str, ...] = ()
    #: 在它那个站里是第几个找到的(站点给的先后)。
    order: int = 0

    def out(self) -> dict[str, Any]:
        return {"source": self.source, "repo": self.repo, "title": self.title, "filename": self.filename, "url": self.url,
                "page": self.page, "size": self.size, "base_model": self.base_model, "exact": self.tier == 0}


# --- 记一会儿 -----------------------------------------------------------------

class _Cache:
    """搜过的记在插件持久目录里(插件每次调用是一个新进程)。没有持久目录就不记。几个站并行地读写,带锁。"""

    def __init__(self) -> None:
        root = os.environ.get("MOSAEL_PLUGIN_DATA_DIR", "")
        self.path = Path(root) / CACHE_FILE if root else None
        saved = load_json(self.path)
        entries = saved.get("entries") if saved.get("version") == CACHE_VERSION else None
        now = time.time()
        self.entries: dict[str, dict[str, Any]] = {
            key: one for key, one in (entries if isinstance(entries, dict) else {}).items()
            if isinstance(one, dict) and isinstance(one.get("until"), (int, float)) and one["until"] > now and "value" in one
        }
        self.dirty = False
        self.lock = threading.Lock()

    def get(self, key: str, ttl: float, compute: Callable[[], Json]) -> Json:
        """记着的(没过期)直接交;没有就现算一个记下。算的时候出错就不记,照样抛出去。"""
        with self.lock:
            hit = self.entries.get(key)
        if hit is not None:
            return hit["value"]
        value = compute()
        with self.lock:
            self.entries[key] = {"until": time.time() + ttl, "value": value}
            self.dirty = True
        return value

    def save(self) -> None:
        if not self.dirty:
            return
        newest = sorted(self.entries.items(), key=lambda item: item[1]["until"])[-MAX_CACHE_ENTRIES:]
        save_json(self.path, {"version": CACHE_VERSION, "entries": dict(newest)})


# --- 一个站 ---------------------------------------------------------------------

class _Site:
    """一个站怎么搜。`run` 依次用要找的那几个词搜,找到同名的就停;搜索请求出错就停下,把已经找到的连同一句原因交回。
    补充的请求(文件大小、文件列表)出错不算这个站失败 —— 除非最后什么都没找到。"""

    name = ""
    label = ""

    def __init__(self, target: _Target, cache: _Cache, locale: str) -> None:
        self.target, self.cache, self.locale = target, cache, locale
        self.found: list[Candidate] = []
        self.urls: set[str] = set()
        #: 补充请求出的第一个错(最后什么都没找到时,拿它当这个站的失败原因)。
        self.trouble = ""

    def queries(self) -> list[str]:
        return self.target.queries

    def run(self) -> tuple[list[Candidate], str]:
        try:
            self.start()
            for query in self.queries():
                if any(one.tier == 0 for one in self.found):
                    break
                self.search(query)
        except ComfyError as exc:
            return self.found, str(exc)
        self.finish()
        return self.found, "" if self.found else self.trouble

    def start(self) -> None:
        """搜之前先做的(HuggingFace:对一遍 Comfy-Org 的仓库)。"""

    def search(self, query: str) -> None:
        raise NotImplementedError

    def finish(self) -> None:
        """搜完补上的(HuggingFace:文件大小)。"""

    def add(self, candidate: Candidate) -> None:
        if candidate.url in self.urls:
            return
        self.urls.add(candidate.url)
        candidate.order = len(self.found)
        self.found.append(candidate)

    def json(self, url: str) -> Json:
        """问一次这个站的接口,交回读出来的 JSON。连不上、超时、限流、拒绝、读不懂,都是给人看的一句(不带令牌)。"""
        label = self.label
        try:
            answer = sources.fetch(url, headers={"Accept": "application/json"}, timeout=TIMEOUT)
        except (ComfyError, OSError, http.client.HTTPException) as exc:
            raise ComfyError(say(self.locale, f"{label} 连不上或超时了", f"{label} didn't answer (unreachable or timed out)")) from exc
        status = answer.status
        if status == 429:
            raise ComfyError(say(self.locale, f"{label} 说请求太频繁,过一会儿再试", f"{label} is rate-limiting searches; try again later"))
        if status in (401, 403):
            raise ComfyError(say(self.locale, f"{label} 拒绝了这次搜索(HTTP {status})", f"{label} refused the search (HTTP {status})"))
        if status != 200:
            raise ComfyError(say(self.locale, f"{label} 回了 HTTP {status}", f"{label} answered HTTP {status}"))
        try:
            return json.loads(answer.body.decode("utf-8"))
        except ValueError as exc:
            raise ComfyError(say(self.locale, f"{label} 回了一段读不懂的东西", f"{label} answered with something unreadable")) from exc

    def parsed(self, url: str, trim: Callable[[Json], Json | None]) -> Json:
        """问一次、剪成要记的那几项。形状不对(接口改了、回的是一句错误)和读不懂一样说。"""
        value = trim(self.json(url))
        if value is None:
            raise ComfyError(say(self.locale, f"{self.label} 回了一段读不懂的东西", f"{self.label} answered with something unreadable"))
        return value

    def extra(self, key: str, ttl: float, compute: Callable[[], Json]) -> Json | None:
        """补充的请求:出错记下原因、交回 None,不打断这个站的搜索。"""
        try:
            return self.cache.get(key, ttl, compute)
        except ComfyError as exc:
            self.trouble = self.trouble or str(exc)
            return None


# --- HuggingFace ------------------------------------------------------------------

def _hf_base(tags: Any, files: list[str]) -> str:
    """仓库标签里写的底模(`base_model:{仓库}`;`base_model:finetune:…` 这种带关系的不算)。底模是按仓库标的,只有仓库里
    只有一个模型文件时才说得准是它的:Comfy-Org 那种一个仓库装好几个模型的,标的常是其中随便一个(flux1-dev 仓库标的是
    FLUX.1-Canny-dev),不写。"""
    if sum(1 for name in files if name.lower().endswith(sources.MODEL_EXTENSIONS)) != 1:
        return ""
    bases = [tag[len("base_model:"):].strip() for tag in tags if isinstance(tag, str) and tag.startswith("base_model:")
             and ":" not in tag[len("base_model:"):]] if isinstance(tags, list) else []
    return bases[0] if len(bases) == 1 else ""


def _hf_repos(data: Json) -> list[dict[str, Any]] | None:
    """`/api/models?…&full=true` 的回答剪成 [{id, files, base}]。"""
    if not isinstance(data, list):
        return None
    repos = []
    for one in data:
        if not isinstance(one, dict) or not isinstance(one.get("id"), str) or one.get("private"):
            continue
        files = [entry["rfilename"] for entry in one.get("siblings") or []
                 if isinstance(entry, dict) and isinstance(entry.get("rfilename"), str)]
        repos.append({"id": one["id"], "files": files, "base": _hf_base(one.get("tags"), files)})
    return repos


def _hf_sizes(data: Json) -> dict[str, int] | None:
    """`/api/models/{仓库}?blobs=true` 的回答剪成 {路径: 大小}。"""
    if not isinstance(data, dict):
        return None
    return {entry["rfilename"]: entry["size"] for entry in data.get("siblings") or []
            if isinstance(entry, dict) and isinstance(entry.get("rfilename"), str) and isinstance(entry.get("size"), int)}


class _HuggingFace(_Site):
    name, label = "huggingface", "HuggingFace"

    def start(self) -> None:
        # Comfy-Org 的清单拉不到不耽误按词搜
        self.take(self.extra("hf:comfy-org", CATALOG_TTL, lambda: self.parsed(HF_CATALOG, _hf_repos)) or [])

    def search(self, query: str) -> None:
        url = "https://huggingface.co/api/models?" + parse.urlencode(
            {"search": query, "full": "true", "limit": SEARCH_LIMIT, "sort": "downloads", "direction": -1})
        self.take(self.cache.get(url, SEARCH_TTL, lambda: self.parsed(url, _hf_repos)))

    def take(self, repos: list[dict[str, Any]]) -> None:
        for repo in repos:
            for path in repo["files"]:
                tier = self.target.tier(path)
                if tier is None:
                    continue
                quoted = parse.quote(path)
                self.add(Candidate(
                    "huggingface", repo["id"], repo["id"], _basename(path),
                    f"https://huggingface.co/{repo['id']}/resolve/main/{quoted}",
                    f"https://huggingface.co/{repo['id']}/blob/main/{quoted}", None, repo["base"], tier, path,
                    tuple(path.split("/")[:-1]),
                ))

    def finish(self) -> None:
        """补大小:先补同名的那几个仓库。问不到就不写大小,候选照样能点。"""
        ranked = sorted(self.found, key=lambda one: (one.tier, one.order))
        for repo in list(dict.fromkeys(one.repo for one in ranked))[:HF_SIZE_LOOKUPS]:
            url = f"https://huggingface.co/api/models/{repo}?" + parse.urlencode({"blobs": "true", "expand[]": "siblings"})
            sizes = self.extra(f"hf:sizes:{repo}", SEARCH_TTL, lambda url=url: self.parsed(url, _hf_sizes)) or {}
            for one in self.found:
                if one.repo == repo:
                    one.size = sizes.get(one.path)


# --- ModelScope -------------------------------------------------------------------

def _ms_repos(data: Json) -> list[str] | None:
    """`/openapi/v1/models?search=` 的回答剪成仓库名。"""
    if not isinstance(data, dict) or data.get("success") is False or not isinstance(data.get("data"), dict):
        return None
    models = data["data"].get("models")
    return [one["id"] for one in models or [] if isinstance(one, dict) and isinstance(one.get("id"), str) and "/" in one["id"]]


def _ms_files(data: Json) -> list[dict[str, Any]] | None:
    """`/api/v1/models/{仓库}/repo/files` 的回答剪成 [{path, size}](只要文件)。"""
    if not isinstance(data, dict) or data.get("Success") is False or not isinstance(data.get("Data"), dict):
        return None
    files = data["Data"].get("Files")
    return [{"path": one["Path"], "size": one.get("Size") if isinstance(one.get("Size"), int) else None}
            for one in files or []
            if isinstance(one, dict) and isinstance(one.get("Path"), str) and one.get("Type", "blob") == "blob"]


def _ms_files_url(repo: str) -> str:
    """仓库默认分支上的全部文件(和 sources 读文件列表同一个接口)。"""
    return f"https://modelscope.cn/api/v1/models/{parse.quote(repo)}/repo/files?" + parse.urlencode(
        {"Revision": "master", "Recursive": "true"})


class _ModelScope(_Site):
    name, label = "modelscope", "ModelScope"

    def __init__(self, target: _Target, cache: _Cache, locale: str) -> None:
        super().__init__(target, cache, locale)
        self.looked: set[str] = set()

    def search(self, query: str) -> None:
        url = "https://modelscope.cn/openapi/v1/models?" + parse.urlencode({"search": query, "page_size": SEARCH_LIMIT})
        repos = [one for one in self.cache.get(url, SEARCH_TTL, lambda: self.parsed(url, _ms_repos)) if one not in self.looked]
        for repo in repos[:MS_FILE_LOOKUPS]:
            self.looked.add(repo)
            files = self.extra(f"ms:files:{repo}", SEARCH_TTL,
                               lambda repo=repo: self.parsed(_ms_files_url(repo), _ms_files))
            for entry in files or []:
                tier = self.target.tier(entry["path"])
                if tier is None:
                    continue
                path = parse.quote(entry["path"])
                self.add(Candidate(
                    "modelscope", repo, repo, _basename(entry["path"]),
                    f"https://modelscope.cn/models/{parse.quote(repo)}/resolve/master/{path}",
                    f"https://modelscope.cn/models/{parse.quote(repo)}/file/view/master/{path}", entry["size"], "", tier,
                    entry["path"], tuple(entry["path"].split("/")[:-1]),
                ))


# --- Civitai ----------------------------------------------------------------------

def _civitai_models(data: Json) -> list[dict[str, Any]] | None:
    """`/api/v1/models?query=` 的回答剪成 [{id, name, type, versions: [{id, name, base, files}]}]。文件只留有下载链接的
    (和 resolve 挑文件时一样),顺序照原样 —— 钉不钉得住看的就是顺序。"""
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        return None
    models = []
    for item in data["items"]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), int):
            continue
        versions = []
        for version in item.get("modelVersions") or []:
            if not isinstance(version, dict) or not isinstance(version.get("id"), int):
                continue
            files = [{"name": str(one.get("name") or ""), "type": str(one.get("type") or ""), "primary": bool(one.get("primary")),
                      "size": int(float(one["sizeKB"]) * 1024) if isinstance(one.get("sizeKB"), (int, float)) else None}
                     for one in version.get("files") or [] if isinstance(one, dict) and one.get("downloadUrl")]
            versions.append({"id": version["id"], "name": str(version.get("name") or "").strip(),
                             "base": str(version.get("baseModel") or "").strip(), "files": files})
        models.append({"id": item["id"], "name": str(item.get("name") or "").strip(), "type": str(item.get("type") or ""),
                       "versions": versions})
    return models


def _civitai_pinned(version_id: int, files: list[dict[str, Any]], index: int) -> str:
    """一个版本里第 `index` 个文件的、resolve 正好解析到它的下载链接;钉不住就是空串。

    resolve(sources._civitai)只看下载链接里的 `type`:带了就取那一类里排第一的文件,没带就取主文件。所以主文件用不带
    `type` 的链接,「那一类里排第一的」用带 `type` 的;同一版本里同类的别的文件钉不住。"""
    chosen = files[index]
    if next((i for i, one in enumerate(files) if one["primary"]), None) == index:
        return f"https://civitai.com/api/download/models/{version_id}"
    if chosen["type"] and next(i for i, one in enumerate(files) if one["type"] == chosen["type"]) == index:
        return f"https://civitai.com/api/download/models/{version_id}?" + parse.urlencode({"type": chosen["type"]})
    return ""


class _Civitai(_Site):
    name, label = "civitai", "Civitai"

    def queries(self) -> list[str]:
        return self.target.queries + ([self.target.words] if self.target.words else [])

    def search(self, query: str) -> None:
        url = "https://civitai.com/api/v1/models?" + parse.urlencode({"query": query, "limit": SEARCH_LIMIT})
        for model in self.cache.get(url, SEARCH_TTL, lambda: self.parsed(url, _civitai_models)):
            folder = sources.CIVITAI_FOLDERS.get(model["type"].lower(), "")
            for version in model["versions"]:
                for index, file in enumerate(version["files"]):
                    tier = self.target.tier(file["name"])
                    link = _civitai_pinned(version["id"], version["files"], index) if tier is not None else ""
                    if not link:
                        continue
                    title = " · ".join(part for part in (model["name"], version["name"]) if part)
                    self.add(Candidate(
                        "civitai", model["name"], title, file["name"], link,
                        f"https://civitai.com/models/{model['id']}?modelVersionId={version['id']}", file["size"],
                        version["base"], tier, file["name"], (folder,) if folder else (),
                    ))


SITE_CLASSES: tuple[type[_Site], ...] = (_HuggingFace, _ModelScope, _Civitai)


# --- op: search_sources --------------------------------------------------------------

def rank(candidates: list[Candidate], folder: str = "") -> list[Candidate]:
    """同名的在前;同一档里目录对得上的在前,再按站;同名的同一个站里按站点给的先后,近似的按大小(小的在前)。
    最多 MAX_CANDIDATES 个,一个站最多 PER_SITE 个。"""

    def key(one: Candidate) -> tuple[Any, ...]:
        elsewhere = 1 if folder and folder not in one.folders else 0
        size = (one.size is None, one.size or 0) if one.tier else (False, 0)
        return one.tier, elsewhere, SITES.index(one.source), size, one.order

    picked: list[Candidate] = []
    per_site: dict[str, int] = {}
    for one in sorted(candidates, key=key):
        if per_site.get(one.source, 0) >= PER_SITE:
            continue
        per_site[one.source] = per_site.get(one.source, 0) + 1
        picked.append(one)
        if len(picked) >= MAX_CANDIDATES:
            break
    return picked


def search(payload: dict[str, Any], _comfy: Comfy, locale: str) -> dict[str, Any]:
    filename = _basename(str(payload.get("filename") or ""))[:300]
    if not filename:
        raise ComfyError(say(locale, "要找的模型文件名是空的", "The model file name to search for is empty"))
    folder = str(payload.get("folder") or "").strip()
    target = _Target(filename)
    cache = _Cache()
    sites = [site(target, cache, locale) for site in SITE_CLASSES]
    with ThreadPoolExecutor(max_workers=len(sites)) as pool:
        results = list(pool.map(lambda site: site.run(), sites))
    cache.save()
    candidates = rank([one for found, _ in results for one in found], folder)
    return {
        "filename": filename,
        "candidates": [one.out() for one in candidates],
        "failed": [{"source": site.name, "message": message} for site, (_, message) in zip(sites, results) if message],
    }
