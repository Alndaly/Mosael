"""在 Civitai 上找这台服务器上的一个模型文件(ADR 0038 §9),找到的记进来源(provenance):来源页、NSFW 标记、示例图、
Civitai 登记的底模都从这一次查询来。

    {"op": "lookup", "folder", "name", "size"?, "refresh"?}
        → {"match": "sha256" | "filename" | "none", "page", "civitai"?, "sha256"?, "note"}

先认已经知道的:经 Mosael 从 Civitai 下的、查过的,直接交记录(`refresh` 才重查)。否则:

1. **按 SHA256**(装了 ComfyUI-Custom-Scripts 时,见 previews):那台机器算出文件的哈希,问 Civitai
   `/api/v1/model-versions/by-hash/{sha256}` —— 对上的就是这个文件,精确到版本;
2. **按文件名和大小**(没有算哈希的路时):在 Civitai 上按文件名搜,只认「Civitai 记的原始文件名一字不差、大小差不过 1 KB」
   **恰好一个版本**的 —— 几个都像就不认,一个都不像也不猜。标 `filename`:存回 ComfyUI 之前要用户确认。

查不到(Civitai 上没有这个文件)也记下来(`match: none` 和查的时间),批量补图时一阵子内不再让那台机器算一遍哈希。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib import parse

import civitai
import previews
import provenance
import sources
from comfy_http import Comfy
from lines import ComfyError, say
from model_files import files_in, norm

#: 算一个大文件的哈希要多久:pysssss 把整个文件读进来再算,几十 GB 的视频模型在机械盘上要好几分钟。
HASH_TIMEOUT_SECONDS = 900.0
#: 按文件名找时,Civitai 记的大小(KB,带小数)和这个文件的大小最多差多少字节。
SIZE_SLACK = 1024
#: 按文件名搜时看几个结果。
SEARCH_LIMIT = 20


def known(record: dict[str, Any] | None) -> bool:
    """这条记录是不是已经说清了 Civitai 上有没有这个文件:从 Civitai 下的、查过的(`checked`)。"""
    return bool(record) and (bool(record.get("civitai")) or bool(record.get("checked")))


def _hash(comfy: Comfy, folder: str, name: str, locale: str) -> str:
    """那台机器算的 SHA256(pysssss 的 `/pysssss/metadata`,第一次要把整个文件读一遍)。"""
    try:
        found = comfy.get(f"/pysssss/metadata/{previews.model_path(folder, name)}", timeout=HASH_TIMEOUT_SECONDS)
    except ComfyError as exc:
        if exc.status == 404:
            raise ComfyError(say(locale, "ComfyUI-Custom-Scripts 找不到这个文件(它刚被挪走或改名了?):重新读一遍模型库再试",
                                 "ComfyUI-Custom-Scripts can't find this file (moved or renamed?). Reload the model library "
                                 "and try again")) from exc
        raise
    digest = str(found.get("pysssss.sha256") or "").strip().lower() if isinstance(found, dict) else ""
    if not civitai.SHA256.match(digest):
        raise ComfyError(say(locale, "ComfyUI-Custom-Scripts 没算出这个文件的 SHA256", "ComfyUI-Custom-Scripts didn't return a SHA256"))
    return digest


def _search_by_filename(name: str, size: int | None, locale: str) -> list[dict[str, Any]]:
    """在 Civitai 上按文件名搜:回 Civitai 记的原始文件名一字不差(不分大小写)、大小差不过 1 KB 的那些版本。"""
    filename = norm(name).rsplit("/", 1)[-1]
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", filename)
    query = parse.urlencode({"query": stem, "limit": SEARCH_LIMIT})
    answer = sources.fetch(f"https://civitai.com/api/v1/models?{query}", headers={"Accept": "application/json"})
    if answer.status != 200:
        raise ComfyError(say(locale, f"Civitai 回了 HTTP {answer.status}", f"Civitai answered HTTP {answer.status}"))
    try:
        found = json.loads(answer.body.decode("utf-8"))
    except ValueError as exc:
        raise ComfyError(say(locale, "Civitai 回了一段读不懂的东西", "Civitai answered with something unreadable")) from exc
    matches: dict[int, dict[str, Any]] = {}
    for item in found.get("items") or [] if isinstance(found, dict) else []:
        if not isinstance(item, dict):
            continue
        for version in item.get("modelVersions") or []:
            if not isinstance(version, dict):
                continue
            for file in version.get("files") or []:
                if not isinstance(file, dict) or str(file.get("name") or "").lower() != filename.lower():
                    continue
                kb = file.get("sizeKB")
                if size is not None and (not isinstance(kb, (int, float)) or abs(kb * 1024 - size) > SIZE_SLACK):
                    continue
                shaped = {**version, "modelId": item.get("id"),
                          "model": {"name": item.get("name"), "type": item.get("type"), "nsfw": item.get("nsfw")}}
                info = civitai.essentials(shaped)
                if info:
                    matches[info["version_id"]] = info
    return list(matches.values())


def _size(comfy: Comfy, folder: str, name: str) -> int | None:
    wanted = norm(name)
    for item in files_in(comfy, folder):
        if norm(str(item.get("name") or "")) == wanted:
            size = item.get("size")
            return size if isinstance(size, int) else None
    return None


def lookup(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    folder, name = str(payload.get("folder") or "").strip(), str(payload.get("name") or "").strip()
    if not folder or not name:
        raise ComfyError(say(locale, "要找哪个文件?目录和名字都要给", "Which file? Give both the folder and the name"))
    size = _size(comfy, folder, name)
    record = provenance.find(provenance.load(comfy), folder, name, size)
    if known(record) and not payload.get("refresh"):
        return _answer(record, locale)
    ways = previews.tools(comfy)
    if ways["hash"]:
        digest = _hash(comfy, folder, name, locale)
        info = civitai.by_hash(digest, locale)
        entry: dict[str, Any] = {"how": "sha256" if info else "none", "sha256": digest, "checked": round(time.time())}
    else:
        candidates = _search_by_filename(name, size, locale)
        info = candidates[0] if len(candidates) == 1 else None
        entry = {"how": "filename" if info else "none", "checked": round(time.time())}
        if len(candidates) > 1:
            entry["ambiguous"] = len(candidates)
    if info:
        entry.update({"site": "civitai", "page": info["page"], "civitai": info})
    elif record and record.get("how") == "download":
        # 经 Mosael 下载的(HuggingFace、ModelScope……):记录里的来源页留着,只是 Civitai 上没有它
        entry = {**record, "checked": entry["checked"]}
    provenance.record(comfy, folder, name, size, entry)
    return _answer(entry, locale)


def _answer(record: dict[str, Any], locale: str) -> dict[str, Any]:
    info = record.get("civitai") if isinstance(record.get("civitai"), dict) else None
    how = str(record.get("how") or "")
    match = how if how in ("sha256", "filename") else ("download" if info else "none")
    if info:
        note = say(locale, "按文件名和大小在 Civitai 上对上的,存回 ComfyUI 之前请确认是同一个文件",
                   "Matched on Civitai by file name and size; confirm it's the same file before saving back to ComfyUI") \
            if how == "filename" else ""
    elif record.get("ambiguous"):
        note = say(locale, f"Civitai 上有 {record['ambiguous']} 个版本的文件名和大小都对得上,分不出是哪一个,不猜",
                   f"{record['ambiguous']} Civitai versions match this file's name and size; it's unclear which, so none is picked")
    else:
        note = say(locale, "Civitai 上没找到这个文件", "This file isn't on Civitai")
    out: dict[str, Any] = {"match": match, "page": str(record.get("page") or ""), "note": note,
                           "remote_previews": civitai.remote_previews(info)}
    if info:
        out["civitai"] = info
    if record.get("sha256"):
        out["sha256"] = record["sha256"]
    return out
