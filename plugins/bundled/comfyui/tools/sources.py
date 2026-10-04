"""一个链接指的是哪个模型文件(ADR 0034 §4):HuggingFace、Civitai、别的直链 —— 以及去这些站的那一个出网口。

    {"op": "resolve", "url": "…"} → 直链、文件名、大小、建议的目录、底模家族、触发词、同名文件在不在

**令牌只发给它自己那个站**:HuggingFace 的令牌(连接凭据 `huggingface_token`)只带给 huggingface.co,Civitai 的
(`civitai_token`)只带给 civitai.com。跳转不自动跟:两个站都会把下载跳到别家的存储(CDN、对象存储)上,urllib 自己跟
跳转时会把 Authorization 头原样带过去 —— 这里每一跳自己判,换了站就不带。令牌不进结果、不进报错。

和 ComfyUI 说话不走代理(局域网);去这些站走宿主给这个连接的出站(环境变量里的代理,没有就照系统的)。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from families import family_from_base
from comfy_http import Comfy
from lines import ComfyError, say
from model_files import folder_info, free_name, names_in, norm

HF_HOSTS = frozenset({"huggingface.co", "www.huggingface.co", "hf.co"})
CIVITAI_HOSTS = frozenset({"civitai.com", "www.civitai.com"})
#: Civitai 的模型类型 → ComfyUI 的模型目录(这台服务器上没有那个目录就不建议)。
CIVITAI_FOLDERS = {
    "checkpoint": "checkpoints",
    "lora": "loras",
    "locon": "loras",
    "dora": "loras",
    "lycoris": "loras",
    "textualinversion": "embeddings",
    "vae": "vae",
    "controlnet": "controlnet",
    "upscaler": "upscale_models",
    "hypernetwork": "hypernetworks",
    "motionmodule": "animatediff_models",
}
USER_AGENT = "Mosael-ComfyUI-plugin"
#: 一问一答最多读多少(Civitai 的版本接口几 KB)。
MAX_SMALL = 4 * 1024 * 1024
#: 跟跳转最多几跳。
MAX_HOPS = 6


@dataclass
class Answer:
    status: int
    headers: dict[str, str]
    body: bytes
    url: str


class _NoRedirect(request.HTTPRedirectHandler):
    """不自动跟跳转:每一跳由 `follow` 自己判要不要带令牌。"""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


#: 默认的处理器(含按环境变量走代理),只换掉跟跳转的那一个。
_OPENER = request.build_opener(_NoRedirect)


def _host(url: str) -> str:
    return (parse.urlsplit(url).hostname or "").lower()


def token_for(url: str) -> str:
    """这个地址该带哪个令牌:只认它自己那个站的。"""
    host = _host(url)
    if host in HF_HOSTS:
        return os.environ.get("HUGGINGFACE_TOKEN", "").strip()
    if host in CIVITAI_HOSTS:
        return os.environ.get("CIVITAI_TOKEN", "").strip()
    return ""


def auth_for(url: str) -> dict[str, str]:
    token = token_for(url)
    return {"Authorization": f"Bearer {token}"} if token else {}


def open_url(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, timeout: float = 30):
    """开一个请求,不跟跳转。3xx 照常交回(由 HTTPError 带着头)。连不上的报给人看的一句(不带令牌)。"""
    req = request.Request(url, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        return _OPENER.open(req, timeout=timeout)
    except error.HTTPError as exc:
        return exc
    except (error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ComfyError(f"{_host(url)}: {reason}") from exc


def fetch(url: str, *, method: str = "GET", headers: dict[str, str] | None = None, timeout: float = 30) -> Answer:
    """一问一答(HEAD,或回答很小的 GET)。不跟跳转。"""
    response = open_url(url, method=method, headers=headers, timeout=timeout)
    try:
        body = response.read(MAX_SMALL) if method == "GET" else b""
        status = getattr(response, "status", None) or getattr(response, "code", 0)
        return Answer(status=int(status), headers={k.lower(): v for k, v in response.headers.items()}, body=body, url=url)
    finally:
        response.close()


def follow(url: str, *, method: str = "HEAD") -> Answer:
    """跟着跳转问到头。每一跳只带**那一跳的站**自己的令牌;HuggingFace 在第一跳就给了 `x-linked-size`,问到那儿就够。"""
    current = url
    for _ in range(MAX_HOPS):
        answer = fetch(current, method=method, headers=auth_for(current))
        location = answer.headers.get("location")
        if answer.status in (301, 302, 303, 307, 308) and location:
            if answer.headers.get("x-linked-size"):
                return answer
            current = parse.urljoin(current, location)
            continue
        return Answer(answer.status, answer.headers, answer.body, current)
    raise ComfyError(f"{_host(url)}: too many redirects")


def _size(headers: dict[str, str]) -> int | None:
    for key in ("x-linked-size", "content-length"):
        raw = headers.get(key, "")
        if raw.isdigit():
            return int(raw)
    return None


def _disposition_name(headers: dict[str, str]) -> str:
    raw = headers.get("content-disposition", "")
    found = re.search(r"filename\*=UTF-8''([^;]+)", raw, re.IGNORECASE)
    if found:
        return parse.unquote(found.group(1)).strip().strip('"')
    found = re.search(r'filename="?([^";]+)"?', raw, re.IGNORECASE)
    return found.group(1).strip() if found else ""


def _safe_name(name: str) -> str:
    """去掉路径(只留最后一段)、`..` 和控制字符;剩下空的就是空串。"""
    last = re.split(r"[\\/]", name.strip())[-1]
    cleaned = "".join(char for char in last if ord(char) >= 32 and char not in ':*?"<>|').strip()
    return "" if cleaned in ("", ".", "..") else cleaned


@dataclass
class Link:
    source: str
    url: str
    filename: str
    size: int | None = None
    folder: str = ""
    family: str = ""
    triggers: list[str] | None = None
    title: str = ""
    page: str = ""
    note: str = ""


# --- HuggingFace --------------------------------------------------------------

_HF_FILE = re.compile(r"^/(?P<repo>(?:datasets/|spaces/)?[^/]+/[^/]+)/(?:blob|resolve)/(?P<rev>[^/]+)/(?P<path>.+)$")


def _huggingface(url: str, locale: str, folders: set[str]) -> Link:
    parts = parse.urlsplit(url)
    found = _HF_FILE.match(parts.path)
    if not found:
        raise ComfyError(say(
            locale,
            "这是 HuggingFace 上的一个仓库页面,不是一个文件:打开仓库的「Files」页,点进要下的那个文件,复制它的地址再贴进来",
            "This is a HuggingFace repository page, not a file. Open the repository's Files tab, click the file you want "
            "and paste that address instead.",
        ))
    repo, rev, path = found.group("repo"), found.group("rev"), found.group("path")
    direct = f"https://huggingface.co/{repo}/resolve/{rev}/{path}"
    head = follow(direct)
    if head.status in (401, 403):
        gated = head.headers.get("x-error-code", "").lower() == "gatedrepo"
        has_token = bool(token_for(direct))
        if gated and not has_token:
            message = say(locale,
                          "这个仓库要先同意条款才能下:在 HuggingFace 网页上登录、同意,再把 HuggingFace 令牌填进这个连接的凭据",
                          "This repository is gated: log in on HuggingFace, accept its terms, then enter a HuggingFace token in this connection's credentials")
        elif gated:
            message = say(locale, "这个仓库要先同意条款:用填了令牌的那个账号在 HuggingFace 网页上同意之后再试",
                          "This repository is gated: accept its terms on HuggingFace with the account whose token you entered, then try again")
        else:
            message = say(locale, "HuggingFace 不让下这个文件(私有仓库?):在这个连接的凭据里填一个有权限的 HuggingFace 令牌",
                          "HuggingFace refused this file (a private repository?). Enter a HuggingFace token that can read it in this connection's credentials")
        raise ComfyError(message)
    if head.status == 404:
        raise ComfyError(say(locale, "HuggingFace 上没有这个文件(仓库、分支或路径不对)",
                             "HuggingFace has no such file (wrong repository, branch or path)"))
    segments = [parse.unquote(one) for one in path.split("/")[:-1]]
    # 官方的拆分仓库(Comfy-Org/…)按 ComfyUI 的目录名放文件:路径里正好有这台服务器上的某个目录名,就建议它
    folder = next((one for one in reversed(segments) if one in folders), "")
    filename = _safe_name(parse.unquote(path.split("/")[-1]))
    return Link("huggingface", direct, filename, _size(head.headers), folder,
                page=f"https://huggingface.co/{repo}/blob/{rev}/{path}")


# --- Civitai ----------------------------------------------------------------------

def _civitai_json(path: str, locale: str) -> dict[str, Any]:
    url = f"https://civitai.com{path}"
    answer = fetch(url, headers={"Accept": "application/json", **auth_for(url)})
    if answer.status == 404:
        raise ComfyError(say(locale, "Civitai 上没有这个模型(或者它已经下架)", "Civitai has no such model (or it was taken down)"))
    if answer.status in (401, 403):
        raise ComfyError(say(locale, "Civitai 不让看这个模型:在这个连接的凭据里填 Civitai 令牌(API Key)",
                             "Civitai refused this model. Enter a Civitai token (API key) in this connection's credentials"))
    if answer.status != 200:
        raise ComfyError(say(locale, f"Civitai 回了 HTTP {answer.status}", f"Civitai answered HTTP {answer.status}"))
    try:
        found = json.loads(answer.body.decode("utf-8"))
    except ValueError as exc:
        raise ComfyError(say(locale, "Civitai 回了一段读不懂的东西", "Civitai answered with something unreadable")) from exc
    return found if isinstance(found, dict) else {}


def _civitai(url: str, locale: str, folders: set[str]) -> Link:
    parts = parse.urlsplit(url)
    query = parse.parse_qs(parts.query)
    version_id = ""
    wanted_type = (query.get("type") or [""])[0]
    if found := re.match(r"^/api/download/models/(\d+)", parts.path):
        version_id = found.group(1)
    elif found := re.match(r"^/api/v1/model-versions/(\d+)", parts.path):
        version_id = found.group(1)
    elif found := re.match(r"^/models/(\d+)", parts.path):
        version_id = (query.get("modelVersionId") or [""])[0]
        if not version_id:
            model = _civitai_json(f"/api/v1/models/{found.group(1)}", locale)
            versions = [one for one in model.get("modelVersions") or [] if isinstance(one, dict)]
            if not versions:
                raise ComfyError(say(locale, "这个 Civitai 模型没有可下载的版本", "This Civitai model has no downloadable version"))
            version_id = str(versions[0].get("id") or "")
    if not version_id:
        raise ComfyError(say(locale, "认不出这是 Civitai 上的哪个模型:贴模型页的地址(带 modelVersionId 更准)或它的下载链接",
                             "Can't tell which Civitai model this is. Paste the model page (with modelVersionId to pick a version) or its download link"))
    version = _civitai_json(f"/api/v1/model-versions/{version_id}", locale)
    files = [one for one in version.get("files") or [] if isinstance(one, dict) and one.get("downloadUrl")]
    chosen = next((one for one in files if wanted_type and one.get("type") == wanted_type), None) \
        or next((one for one in files if one.get("primary")), None) \
        or next((one for one in files if one.get("type") == "Model"), None) \
        or (files[0] if files else None)
    if chosen is None:
        raise ComfyError(say(locale, "这个 Civitai 版本没有可下载的文件", "This Civitai version has no downloadable file"))
    model = version.get("model") if isinstance(version.get("model"), dict) else {}
    kind = str(model.get("type") or "").lower()
    folder = CIVITAI_FOLDERS.get(kind, "")
    base = str(version.get("baseModel") or "").strip()
    family = family_from_base(base)
    size_kb = chosen.get("sizeKB")
    title = " · ".join(part for part in (str(model.get("name") or "").strip(), str(version.get("name") or "").strip()) if part)
    model_id = version.get("modelId") or ""
    return Link(
        "civitai", str(chosen["downloadUrl"]), _safe_name(str(chosen.get("name") or "")),
        int(float(size_kb) * 1024) if isinstance(size_kb, (int, float)) else None,
        folder if folder in folders else "", family,
        [str(one).strip() for one in version.get("trainedWords") or [] if str(one).strip()][:30], title,
        page=f"https://civitai.com/models/{model_id}?modelVersionId={version_id}" if model_id else "",
    )


# --- 别的直链 ------------------------------------------------------------------

def _direct(url: str, locale: str) -> Link:
    head = follow(url)
    if head.status >= 400:
        raise ComfyError(say(locale, f"这个链接回了 HTTP {head.status},下不了", f"This link answered HTTP {head.status}; it can't be downloaded"))
    kind = head.headers.get("content-type", "").lower()
    if kind.startswith("text/html"):
        raise ComfyError(say(locale, "这个链接打开的是一个网页,不是模型文件:找到页面上的下载按钮,复制它的链接再贴进来",
                             "This link opens a web page, not a model file. Copy the link behind the page's download button instead"))
    name = _safe_name(_disposition_name(head.headers)) or _safe_name(parse.unquote(parse.urlsplit(head.url).path.split("/")[-1]))
    return Link("direct", url, name, _size(head.headers))


# --- op: resolve ----------------------------------------------------------------

def link_for(url: str, locale: str, folders: set[str]) -> Link:
    if not url.startswith(("http://", "https://")):
        raise ComfyError(say(locale, "这不是一个能下载的链接:要以 http:// 或 https:// 开头",
                             "This is not a downloadable link: it must start with http:// or https://"))
    host = _host(url)
    if host in HF_HOSTS:
        return _huggingface(url, locale, folders)
    if host in CIVITAI_HOSTS:
        return _civitai(url, locale, folders)
    return _direct(url, locale)


def direct_url(url: str, locale: str, folders: set[str]) -> str:
    """下载时用的直链:HuggingFace 的 `/blob/` 换成 `/resolve/`、Civitai 的模型页换成下载链接;别的原样。"""
    host = _host(url)
    if host in HF_HOSTS:
        found = _HF_FILE.match(parse.urlsplit(url).path)
        if found:
            return f"https://huggingface.co/{found.group('repo')}/resolve/{found.group('rev')}/{found.group('path')}"
        return url
    if host in CIVITAI_HOSTS and not parse.urlsplit(url).path.startswith("/api/download/"):
        return link_for(url, locale, folders).url
    return url


def resolve(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    info = folder_info(comfy) or {}
    folders = set(info)
    link = link_for(url, locale, folders)
    if not link.filename:
        raise ComfyError(say(locale, "从这个链接看不出文件名,下不了", "Can't tell the file name from this link"))
    exists, suggestion = False, ""
    if link.folder:
        taken = names_in(comfy, link.folder)
        exists = norm(link.filename) in taken
        suggestion = free_name(link.filename, taken) if exists else ""
    return {
        "source": link.source, "url": link.url, "page": link.page, "filename": link.filename, "size": link.size,
        "folder": link.folder, "family": link.family, "triggers": link.triggers or [], "title": link.title,
        "exists": exists, "suggested_filename": suggestion, "note": link.note,
    }
