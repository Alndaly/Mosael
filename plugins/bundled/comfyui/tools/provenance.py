"""这台服务器上的一个模型文件从哪来(ADR 0038 §9):来源页,对上了 Civitai 的哪个版本。

两种时候记下来:

- **经 Mosael 下载时**(`how: "download"`):下载框解析出的那一页 —— HuggingFace 的文件页、Civitai 的版本页、
  ModelScope 的文件页;Civitai 的还连着那个版本的信息(NSFW、示例图、底模,见 civitai.essentials)。贴的是别的直链就
  只记「经 Mosael 下载」,不记页 —— 一个下载地址不是模型的介绍页;
- **按文件在 Civitai 上查到时**(`how: "sha256"` 按哈希、`"filename"` 按 Civitai 上记的原始文件名和大小):见 lookup。

记在插件的持久目录里(按服务器分,见 model_files.data_file),键是「目录/名字」,带着记下时的大小:同名的文件换了
(大小不同)就不算数。这不是缓存 —— 下载时的来源页事后找不回来,按哈希查一次要那台服务器把整个文件读一遍。

「下载的这个链接是哪一页」那一步(`provenance_of`)也在这里:它要问一次 Civitai 的接口,而 `civitai` 又要从
`sources` 出网(`sources.fetch`)—— 留在 `sources` 就是那两个模块互相认识(见 `provenance_of` 的说明)。
"""

from __future__ import annotations

import time
from typing import Any
from urllib import parse

import civitai
import civitai_urls
import sources
from comfy_http import Comfy
from lines import ComfyError
from model_files import data_file, load_json, norm, save_json

#: 记录的形状版本。形状要变时随插件带一段改写(插件里不留认旧形状的分支)。
VERSION = 1


def provenance_of(url: str, locale: str) -> dict[str, Any]:
    """下载的这个链接是哪个站上的哪一页(经 Mosael 下载时记下):HuggingFace 的文件页、Civitai 的版本页
    (连着那个版本的信息)、ModelScope 的文件页。别的直链只记站点,不记页 —— 下载地址不是介绍页。

    **住在这里而不是 sources**:这一步要问一次 Civitai 的接口(`civitai.version`),而 `civitai` 又要从
    `sources` 出网(`sources.fetch`)—— 留在 sources 就是那两个模块互相认识。链接的形状仍是 sources 的事
    (哪种直链、那一页怎么拼),这里只把「哪一页」和那个版本的信息凑成一条要记下来的来源。

    尽力而为:问 Civitai 失败(断网、限流)不该挡住下载,那时只记站点。"""
    url = sources.canonical_url(url)
    host = sources._host(url)
    if host in sources.HF_HOSTS:
        found = sources._HF_FILE.match(parse.urlsplit(url).path)
        if found:
            return {"site": "huggingface",
                    "page": f"https://huggingface.co/{found.group('repo')}/blob/{found.group('rev')}/{found.group('path')}"}
        return {"site": "huggingface"}
    if host in sources.CIVITAI_HOSTS:
        version_id = civitai_urls.version_id_of(url)
        try:
            info = civitai.version(version_id, locale) if version_id else None
        except (ComfyError, OSError):
            info = None
        return {"site": "civitai", "page": info["page"], "civitai": info} if info else {"site": "civitai"}
    if host in sources.MODELSCOPE_HOSTS:
        try:
            target = sources._ms_link(url, locale)
        except ComfyError:
            return {"site": "modelscope"}
        base = f"https://{target.site}/models/{parse.quote(target.repo)}"
        if target.path:
            return {"site": "modelscope", "page": f"{base}/file/view/{parse.quote(target.revision or 'master', safe='')}/"
                                                  f"{parse.quote(target.path)}"}
        return {"site": "modelscope", "page": base}
    return {"site": "direct"}


def _key(folder: str, name: str) -> str:
    return f"{folder}/{norm(name)}"


def load(comfy: Comfy) -> dict[str, dict[str, Any]]:
    """这台服务器上记着的全部:「目录/名字」→ 记录。"""
    found = load_json(data_file(comfy, "provenance"))
    files = found.get("files") if found.get("version") == VERSION else None
    return {key: value for key, value in (files or {}).items() if isinstance(value, dict)}


def find(records: dict[str, dict[str, Any]], folder: str, name: str, size: Any) -> dict[str, Any] | None:
    """一个文件的记录;没有、或文件换了(大小对不上)→ None。"""
    found = records.get(_key(folder, name))
    if found is None:
        return None
    if isinstance(size, int) and isinstance(found.get("size"), int) and found["size"] != size:
        return None
    return found


def record(comfy: Comfy, folder: str, name: str, size: Any, entry: dict[str, Any]) -> None:
    """记下(覆盖这个文件之前的那条)。`entry`:`how`、`page`、`site`,Civitai 的有 `civitai`,按哈希查的有 `sha256`。"""
    path = data_file(comfy, "provenance")
    found = load_json(path)
    files = found.get("files") if found.get("version") == VERSION and isinstance(found.get("files"), dict) else {}
    files[_key(folder, name)] = {**entry, "size": size if isinstance(size, int) else None, "at": round(time.time())}
    save_json(path, {"version": VERSION, "files": files})
