"""Civitai 上的一个模型版本:读它的公开接口、收成模型库要的那几样(ADR 0038 §9)。

模型库要 Civitai 的东西有四样,都出自同一份「版本」信息(`/api/v1/model-versions/{版本}`,按哈希查是
`/api/v1/model-versions/by-hash/{sha256}`,回的是同一种形状):

- **来源页**:`https://civitai.com/models/{模型}?modelVersionId={版本}`;
- **NSFW**:模型上的 `nsfw`(作者 / 站方标的「这是成人内容的模型」),每张示例图自己的 `nsfwLevel`
  (1 PG、2 PG-13、4 R、8 X、16 XXX,32 是站方屏蔽的);
- **示例图 / 示例视频**:没有预览图的模型拿它当预览;
- **底模**:`baseModel`(「Illustrious」「Wan Video 2.2 T2V-A14B」……),权重只看得出 SDXL / Wan 时拿它细分。

公开的信息不用登录、不带令牌(令牌只给下载要登录的模型用,见 sources)。Civitai 认请求的 User-Agent:
Python 自己的那个(`Python-urllib/3.x`)回 403,所以用 sources 那个浏览器式的写法。
"""

from __future__ import annotations

import json
import re
from typing import Any
from urllib import parse

import sources
from lines import ComfyError, say

#: 示例图最多记几张(挑预览图用;作者常传十几二十张,前面的就够挑)。
MAX_IMAGES = 12
#: 示例图的地址只认 Civitai 自己的图床:这一格最后交给宿主去取,不替别的地址背书。
MEDIA_HOST = "image.civitai.com"
#: Civitai 的分级里 R(4)起算成人内容 —— 和它自己网站上「只看安全内容」的开关同一条线(PG、PG-13 之外的都藏)。
NSFW_FROM_LEVEL = 4
#: 一个 sha256 长什么样(Civitai 收大写、小写都行)。
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def page(model_id: Any, version_id: Any) -> str:
    """一个版本在 Civitai 网站上的那一页。"""
    return f"https://civitai.com/models/{int(model_id)}?modelVersionId={int(version_id)}"


def _get(path: str, locale: str) -> dict[str, Any] | None:
    """一问一答。没有(404)→ None;别的不对 → 说清楚。"""
    answer = sources.fetch(f"https://civitai.com{path}", headers={"Accept": "application/json"})
    if answer.status == 404:
        return None
    if answer.status != 200:
        raise ComfyError(say(locale, f"Civitai 回了 HTTP {answer.status}", f"Civitai answered HTTP {answer.status}"))
    try:
        found = json.loads(answer.body.decode("utf-8"))
    except ValueError as exc:
        raise ComfyError(say(locale, "Civitai 回了一段读不懂的东西", "Civitai answered with something unreadable")) from exc
    return found if isinstance(found, dict) else None


def version(version_id: int | str, locale: str) -> dict[str, Any] | None:
    """一个版本的信息(收好的那几样,见 `essentials`);Civitai 上没有 → None。"""
    found = _get(f"/api/v1/model-versions/{int(version_id)}", locale)
    return essentials(found) if found else None


def by_hash(sha256: str, locale: str) -> dict[str, Any] | None:
    """按文件的 SHA256 问是哪个版本;Civitai 上没有这个文件 → None。"""
    if not SHA256.match(sha256 or ""):
        return None
    found = _get(f"/api/v1/model-versions/by-hash/{sha256.upper()}", locale)
    return essentials(found) if found else None


def _int(value: Any) -> int:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _media(raw: Any) -> dict[str, Any] | None:
    """一张示例图(或一段示例视频):地址、种类、分级、宽高。不是 Civitai 图床上的地址不收。"""
    if not isinstance(raw, dict) or not isinstance(raw.get("url"), str):
        return None
    url = raw["url"].strip()
    parts = parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname != MEDIA_HOST:
        return None
    level = _int(raw.get("nsfwLevel"))
    if level >= 32:
        return None  # 站方屏蔽的
    kind = "video" if str(raw.get("type") or "").lower() == "video" else "image"
    return {
        "url": url,
        "preview": sized(url, kind),
        "kind": kind,
        "level": level,
        "width": _int(raw.get("width")),
        "height": _int(raw.get("height")),
    }


def sized(url: str, kind: str) -> str:
    """示例图的 512 宽那一份(Civitai 图床按地址里倒数第二段转:`original=true` 换成 `width=512`;视频换成
    `transcode=true,width=512`)。当预览图用不着原图 —— 原图常是一两千像素、几 MB。"""
    parts = parse.urlsplit(url)
    segments = parts.path.split("/")
    transform = "transcode=true,width=512" if kind == "video" else "width=512"
    if len(segments) >= 5:
        segments[-2] = transform
    else:
        segments.insert(len(segments) - 1, transform)
    return parse.urlunsplit(parts._replace(path="/".join(segments)))


def remote_previews(info: dict[str, Any] | None) -> list[dict[str, Any]]:
    """一个版本的示例,交给宿主当预览图挑(宿主取 `url`,不认识 Civitai):有图就只交图;示例只有视频的(Wan、MiniMax H3
    这类视频模型常这样)交视频 —— 512 宽的转码(`transcode=true,width=512`)。"""
    media = [one for one in (info or {}).get("images") or [] if isinstance(one, dict) and one.get("preview")]
    images = [one for one in media if one.get("kind") == "image"]
    chosen = images or [one for one in media if one.get("kind") == "video"]
    return [{"url": one["preview"], "kind": one["kind"], "site": "civitai", "level": int(one.get("level") or 0),
             "nsfw": flagged(int(one.get("level") or 0))} for one in chosen]


def essentials(raw: dict[str, Any]) -> dict[str, Any] | None:
    """Civitai 回的一个版本 → 模型库要的那几样。认不出(没有模型号、版本号)→ None。"""
    model_id, version_id = _int(raw.get("modelId")), _int(raw.get("id"))
    if not model_id or not version_id:
        return None
    model = raw.get("model") if isinstance(raw.get("model"), dict) else {}
    images = [one for one in (_media(item) for item in raw.get("images") or []) if one][:MAX_IMAGES]
    files = [
        {"name": str(one.get("name") or "")[:300], "size": int(float(one["sizeKB"]) * 1024)
         if isinstance(one.get("sizeKB"), (int, float)) else 0,
         "sha256": str((one.get("hashes") or {}).get("SHA256") or "").lower()}
        for one in raw.get("files") or [] if isinstance(one, dict)
    ]
    return {
        "model_id": model_id,
        "version_id": version_id,
        "page": page(model_id, version_id),
        "title": " · ".join(part for part in (str(model.get("name") or "").strip(),
                                              str(raw.get("name") or "").strip()) if part)[:300],
        "type": str(model.get("type") or "")[:40],
        "base_model": str(raw.get("baseModel") or "").strip()[:80],
        "nsfw": bool(model.get("nsfw")),
        "images": images,
        "files": files[:8],
    }


def flagged(level: int) -> bool:
    """一张示例图的分级算不算成人内容。"""
    return level >= NSFW_FROM_LEVEL


def version_id_of(url: str) -> str:
    """Civitai 的下载链接、版本接口、带 modelVersionId 的模型页 → 版本号;认不出是空串。"""
    parts = parse.urlsplit(url)
    if found := re.match(r"^/api/download/models/(\d+)", parts.path):
        return found.group(1)
    if found := re.match(r"^/api/v1/model-versions/(\d+)", parts.path):
        return found.group(1)
    if re.match(r"^/models/\d+", parts.path):
        return (parse.parse_qs(parts.query).get("modelVersionId") or [""])[0]
    return ""
