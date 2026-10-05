"""一个链接指的是哪个模型文件(ADR 0034 §4):HuggingFace、Civitai、ModelScope、别的直链 —— 以及去这些站的那一个出网口。

    {"op": "resolve", "url": "…"} → 直链、文件名、大小、建议的目录、底模家族、触发词、同名文件在不在

**令牌只发给它自己那个站**:HuggingFace 的令牌(连接凭据 `huggingface_token`)只带给 huggingface.co,Civitai 的
(`civitai_token`)只带给 civitai.com,ModelScope 的(`modelscope_token`)只带给 modelscope.cn 和它的国际站 modelscope.ai。
跳转不自动跟:这几个站都会把下载跳到别处的存储(CDN、对象存储)上,urllib 自己跟跳转时会把 Authorization 头原样带过去
—— 这里每一跳自己判,换了站就不带。令牌不进结果、不进报错。

和 ComfyUI 说话不走代理(局域网);去这些站走宿主给这个连接的出站(环境变量里的代理,没有就照系统的)。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from families import family_from_base, family_from_modelscope
from comfy_http import Comfy
from lines import ComfyError, say
from model_files import folder_info, names_in, norm

HF_HOSTS = frozenset({"huggingface.co", "www.huggingface.co", "hf.co"})
CIVITAI_HOSTS = frozenset({"civitai.com", "www.civitai.com"})
#: Civitai 的另外几个域名(同一个站、同一套接口;用户常从这些域名上复制链接)。一律换成 civitai.com 再问 ——
#: 令牌也就只交给 civitai.com 这一个地方。
CIVITAI_ALIASES = frozenset({"civitai.red", "www.civitai.red", "civitai.green", "www.civitai.green"})
#: ModelScope 的两个站:modelscope.cn 和国际站 modelscope.ai。接口一样,但模型库和账号各是各的(.cn 上的模型 .ai 上
#: 不一定有,一个站的令牌另一个站不认)—— 各问各的,不互相改写。
MODELSCOPE_HOSTS = frozenset({"modelscope.cn", "modelscope.ai"})
#: 带 www. 的是同一个站:换成不带 www. 的再问,令牌也就只交给上面那两个地方。
MODELSCOPE_ALIASES = {"www.modelscope.cn": "modelscope.cn", "www.modelscope.ai": "modelscope.ai"}
#: ModelScope AIGC 专区的模型类型(`AigcType`,它只有这三种)→ ComfyUI 的模型目录。
MODELSCOPE_FOLDERS = {"checkpoint": "checkpoints", "lora": "loras", "vae": "vae"}
#: 贴的是 ModelScope 的模型页时,仓库里哪些文件算模型文件。
MODEL_EXTENSIONS = (".safetensors", ".sft", ".ckpt", ".pt", ".pth", ".bin", ".gguf")
#: 好几个模型文件时报错里最多列几个。
LISTED_CANDIDATES = 10
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
#: 浏览器式的写法:Civitai 对 Python 自己的 User-Agent(`Python-urllib/3.x`)回 403;这样写各站都认,也说得出是谁。
USER_AGENT = "Mozilla/5.0 (compatible; Mosael-ComfyUI-plugin)"
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


def canonical_url(url: str) -> str:
    """别名域名上的链接换成那个站的规范域名上同一个地址:Civitai 别的域名 → civitai.com,ModelScope 带 www. 的 → 不带的;
    别的原样。"""
    parts = parse.urlsplit(url)
    host = (parts.hostname or "").lower()
    if host in CIVITAI_ALIASES:
        return parse.urlunsplit(parts._replace(netloc="civitai.com"))
    if host in MODELSCOPE_ALIASES:
        return parse.urlunsplit(parts._replace(netloc=MODELSCOPE_ALIASES[host]))
    return url


def token_for(url: str) -> str:
    """这个地址该带哪个令牌:只认它自己那个站的。"""
    host = _host(url)
    if host in HF_HOSTS:
        return os.environ.get("HUGGINGFACE_TOKEN", "").strip()
    if host in CIVITAI_HOSTS:
        return os.environ.get("CIVITAI_TOKEN", "").strip()
    if host in MODELSCOPE_HOSTS:
        return os.environ.get("MODELSCOPE_TOKEN", "").strip()
    return ""


def auth_for(url: str) -> dict[str, str]:
    token = token_for(url)
    if not token:
        return {}
    if _host(url) in MODELSCOPE_HOSTS:
        # ModelScope 新接口认 Bearer,老接口(/api/v1)和下载认会话 cookie —— 官方 SDK 两样都带
        return {"Authorization": f"Bearer {token}", "Cookie": f"m_session_id={token}"}
    return {"Authorization": f"Bearer {token}"}


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
    """Civitai 的公开接口。先不带令牌问 —— 公开的模型信息不用登录就看得到,令牌能不发就不发;回 401 / 403
    (要登录才看得到的模型)且填了令牌时,再带上它问一次。"""
    url = f"https://civitai.com{path}"
    answer = fetch(url, headers={"Accept": "application/json"})
    if answer.status in (401, 403) and auth_for(url):
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


#: 链接上能挑版本里哪一个文件的参数:`fileId` 是 Civitai 给每个文件的编号(点名要这一个);另外四个和 Civitai 自己的
#: 下载链接一样(`type` 对文件的种类,`format` / `size` / `fp` 对文件的 metadata),没有对得上的就用主文件。
_CIVITAI_FILE_KEYS = ("type", "format", "size", "fp")


def _civitai_file(files: list[dict[str, Any]], query: dict[str, list[str]], locale: str) -> dict[str, Any] | None:
    """版本里挑哪一个文件:链接点名的(`fileId`,对不上就说对不上,不悄悄换一个),再按种类、格式、精度挑,
    都没说就挑主文件(`primary`),再不然第一个模型文件、第一个文件。"""
    file_id = (query.get("fileId") or [""])[0].strip()
    if file_id:
        named = next((one for one in files if str(one.get("id") or "") == file_id), None)
        if named is None:
            raise ComfyError(say(locale, f"这个 Civitai 版本里没有编号是 {file_id} 的文件",
                                 f"This Civitai version has no file with id {file_id}"))
        return named
    wanted = {key: (query.get(key) or [""])[0].strip().lower() for key in _CIVITAI_FILE_KEYS}

    def fits(one: dict[str, Any]) -> bool:
        meta = one.get("metadata") if isinstance(one.get("metadata"), dict) else {}
        facts = {"type": one.get("type"), **{key: meta.get(key) for key in ("format", "size", "fp")}}
        return all(not want or str(facts[key] or "").strip().lower() == want for key, want in wanted.items())

    return (next((one for one in files if fits(one)), None) if any(wanted.values()) else None) \
        or next((one for one in files if one.get("primary")), None) \
        or next((one for one in files if one.get("type") == "Model"), None) \
        or (files[0] if files else None)


def _civitai(url: str, locale: str, folders: set[str]) -> Link:
    parts = parse.urlsplit(url)
    query = parse.parse_qs(parts.query)
    version_id = ""
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
    chosen = _civitai_file(files, query, locale)
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


# --- ModelScope -------------------------------------------------------------------

@dataclass
class _ModelScopeLink:
    """一个 ModelScope 链接指着哪儿:一个文件(`path`),或一个仓库 / 目录(`root`,在里面找模型文件)。
    `revision` 空着就用仓库的默认分支。"""

    site: str
    repo: str
    revision: str = ""
    path: str = ""
    root: str = ""


def _ms_path(segments: list[str]) -> str:
    # 文件页上路径里的斜杠常被编码成 %2F
    return parse.unquote("/".join(segments)).strip("/")


def _ms_link(url: str, locale: str) -> _ModelScopeLink:
    """认 ModelScope 的几种链接:模型页 `/models/{仓库}`(及 `/summary`、`/files` 这些页签)、目录页 `/tree/{版本}/{目录}`、
    文件页 `/file/view/{版本}/{路径}`、直链 `/resolve/{版本}/{路径}`,以及官方 SDK 的下载地址
    `/api/v1/models/{仓库}/repo?Revision=&FilePath=`。"""
    parts = parse.urlsplit(url)
    site = _host(url)
    if found := re.match(r"^/api/v1/models/([^/]+)/([^/]+)/repo/?$", parts.path):
        query = parse.parse_qs(parts.query)
        repo = f"{parse.unquote(found.group(1))}/{parse.unquote(found.group(2))}"
        return _ModelScopeLink(site, repo, (query.get("Revision") or [""])[0],
                               path=(query.get("FilePath") or [""])[0].strip("/"))
    found = re.match(r"^/models/([^/]+)/([^/]+)(?:/(.*))?$", parts.path)
    if not found:
        raise ComfyError(say(locale, "认不出这是 ModelScope 上的哪个模型:贴模型页的地址,或者模型文件页里那个文件的地址",
                             "Can't tell which ModelScope model this is. Paste the model page, or the address of a file "
                             "from its Files tab"))
    repo = f"{parse.unquote(found.group(1))}/{parse.unquote(found.group(2))}"
    rest = [one for one in (found.group(3) or "").split("/") if one]
    if rest[:2] == ["file", "view"] and len(rest) > 3:
        return _ModelScopeLink(site, repo, parse.unquote(rest[2]), path=_ms_path(rest[3:]))
    if rest[:1] == ["resolve"] and len(rest) > 2:
        return _ModelScopeLink(site, repo, parse.unquote(rest[1]), path=_ms_path(rest[2:]))
    if rest[:1] == ["tree"] and len(rest) > 1:
        return _ModelScopeLink(site, repo, parse.unquote(rest[1]), root=_ms_path(rest[2:]))
    return _ModelScopeLink(site, repo)


def _ms_resolve_url(site: str, repo: str, revision: str, path: str) -> str:
    return f"https://{site}/models/{parse.quote(repo)}/resolve/{parse.quote(revision, safe='')}/{parse.quote(path)}"


def _ms_json(url: str, locale: str, missing: tuple[str, str], *, authed: bool) -> tuple[Any, bool]:
    """ModelScope 的接口,交回 (Data, 这回带没带令牌)。先不带令牌问 —— 公开的模型不用登录就看得到,令牌能不发就不发;
    回 401 / 403,或 404(ModelScope 对看不到的私有模型也回 404)且填了令牌时,再带上它问一次。
    `missing` 是 404 时说的那一句(中、英)。"""
    accept = {"Accept": "application/json"}
    answer = fetch(url, headers={**accept, **(auth_for(url) if authed else {})})
    if not authed and answer.status in (401, 403, 404) and auth_for(url):
        authed = True
        answer = fetch(url, headers={**accept, **auth_for(url)})
    has_token = bool(token_for(url))
    if answer.status == 404:
        hint = say(locale, "(要是私有模型:填的令牌也看不到它)" if has_token else
                   "(要是私有模型:在这个连接的凭据里填一个有权限的 ModelScope 令牌)",
                   " (if it's private, the token you entered can't see it either)" if has_token else
                   " (if it's private, enter a ModelScope token that can read it in this connection's credentials)")
        raise ComfyError(say(locale, f"{missing[0]}{hint}", f"{missing[1]}{hint}"))
    if answer.status in (401, 403):
        raise ComfyError(say(
            locale,
            "ModelScope 不让看这个模型:填的 ModelScope 令牌没有权限(modelscope.cn 和 modelscope.ai 的账号不通用,令牌要是"
            "这个站的)" if has_token else
            "ModelScope 不让看这个模型(私有或要授权):在这个连接的凭据里填 ModelScope 访问令牌",
            "ModelScope refused this model: the ModelScope token you entered has no access (modelscope.cn and modelscope.ai "
            "accounts are separate; the token must be from this site)" if has_token else
            "ModelScope refused this model (private or restricted). Enter a ModelScope access token in this connection's "
            "credentials",
        ))
    if answer.status != 200:
        raise ComfyError(say(locale, f"ModelScope 回了 HTTP {answer.status}", f"ModelScope answered HTTP {answer.status}"))
    try:
        found = json.loads(answer.body.decode("utf-8"))
    except ValueError as exc:
        raise ComfyError(say(locale, "ModelScope 回了一段读不懂的东西", "ModelScope answered with something unreadable")) from exc
    if not isinstance(found, dict) or found.get("Success") is False:
        said = str(found.get("Message") or "")[:200] if isinstance(found, dict) else ""
        raise ComfyError(say(locale, f"ModelScope 没给出这个模型的信息:{said}", f"ModelScope gave no information on this model: {said}"))
    return found.get("Data"), authed


def _ms_files(api: str, revision: str, root: str, *, recursive: bool, locale: str, authed: bool) -> list[dict[str, Any]]:
    """仓库里 `root` 这个目录下的文件(`recursive` 连子目录)。只要文件,不要目录。"""
    query = {"Revision": revision, "Recursive": "true" if recursive else "false", **({"Root": root} if root else {})}
    data, _ = _ms_json(f"{api}/repo/files?{parse.urlencode(query)}", locale,
                       (f"ModelScope 上这个模型没有「{revision}」这个分支或版本",
                        f"This ModelScope model has no branch or version “{revision}”"), authed=authed)
    files = data.get("Files") if isinstance(data, dict) else None
    return [one for one in files or [] if isinstance(one, dict) and one.get("Type", "blob") == "blob" and one.get("Path")]


def _candidates(locale: str, paths: list[str]) -> str:
    shown = paths[:LISTED_CANDIDATES]
    more = len(paths) - len(shown)
    return say(locale, "、".join(shown) + (f" 等 {len(paths)} 个" if more else ""),
               ", ".join(shown) + (f" and {more} more" if more else ""))


def _modelscope(url: str, locale: str, folders: set[str]) -> Link:
    target = _ms_link(url, locale)
    api = f"https://{target.site}/api/v1/models/{parse.quote(target.repo)}"
    info, authed = _ms_json(api, locale, ("ModelScope 上没有这个模型", "ModelScope has no such model"), authed=False)
    info = info if isinstance(info, dict) else {}
    revision = target.revision or str(info.get("Revision") or "") or "master"
    if target.path:
        directory = target.path.rpartition("/")[0]
        entries = _ms_files(api, revision, directory, recursive=False, locale=locale, authed=authed)
        entry = next((one for one in entries if one["Path"] == target.path), None)
        if entry is None:
            raise ComfyError(say(locale, "ModelScope 上这个模型里没有这个文件(分支或路径不对)",
                                 "This ModelScope model has no such file (wrong branch or path)"))
    else:
        # 模型页 / 目录页:只有一个模型文件就是它,好几个就列出来请用户挑
        entries = _ms_files(api, revision, target.root, recursive=True, locale=locale, authed=authed)
        models = [one for one in entries if str(one["Path"]).lower().endswith(MODEL_EXTENSIONS)]
        if not models:
            raise ComfyError(say(locale, "这个 ModelScope 仓库里没有模型文件(.safetensors、.ckpt、.gguf……):贴要下的那个文件的地址",
                                 "This ModelScope repository has no model file (.safetensors, .ckpt, .gguf…). Paste the "
                                 "address of the file you want"))
        if len(models) > 1:
            paths = [str(one["Path"]) for one in models]
            raise ComfyError(say(
                locale,
                f"这个 ModelScope 仓库里有 {len(models)} 个模型文件,不知道要下哪一个:{_candidates(locale, paths)}。"
                "在「模型文件」页点进要下的那个文件,复制它的地址再贴进来",
                f"This ModelScope repository has {len(models)} model files, so it's unclear which one you want: "
                f"{_candidates(locale, paths)}. Open its Files tab, click the file you want and paste that address instead.",
            ))
        entry = models[0]
    path = str(entry["Path"])
    # 目录:AIGC 专区的模型按登记的类型定;推不出就看路径里有没有这台服务器上的某个目录名(官方的拆分仓库按 ComfyUI
    # 的目录名放文件,和 HuggingFace 一样)
    kind = str(info.get("AigcType") or "").strip().lower()
    folder = MODELSCOPE_FOLDERS.get(kind, "")
    if folder not in folders:
        folder = next((one for one in reversed(path.split("/")[:-1]) if one in folders), "")
    # 底模家族只认 AIGC 专区登记的;普通仓库没写,不按名字猜
    bases = [str(one) for one in info.get("BaseModel") or [] if isinstance(one, str)]
    name = str(info.get("Name") or "").strip() or target.repo.split("/")[-1]
    family = family_from_modelscope(str(info.get("VisionFoundation") or ""), bases, (name, path)) if kind else ""
    chinese = str(info.get("ChineseName") or "").strip()
    size = entry.get("Size")
    return Link(
        "modelscope", _ms_resolve_url(target.site, target.repo, revision, path), _safe_name(path.split("/")[-1]),
        size if isinstance(size, int) else None, folder, family,
        [str(one).strip() for one in info.get("TriggerWords") or [] if str(one).strip()][:30],
        say(locale, chinese or name, name),
        page=f"https://{target.site}/models/{parse.quote(target.repo)}/file/view/{parse.quote(revision, safe='')}/"
             f"{parse.quote(path)}",
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
    url = canonical_url(url)
    host = _host(url)
    if host in HF_HOSTS:
        return _huggingface(url, locale, folders)
    if host in CIVITAI_HOSTS:
        return _civitai(url, locale, folders)
    if host in MODELSCOPE_HOSTS:
        return _modelscope(url, locale, folders)
    return _direct(url, locale)


def direct_url(url: str, locale: str, folders: set[str]) -> str:
    """下载时用的直链:HuggingFace 的 `/blob/` 换成 `/resolve/`、Civitai 的模型页换成下载链接、ModelScope 的文件页换成
    `/resolve/`(模型页要先挑出那一个文件);别的原样。"""
    url = canonical_url(url)
    host = _host(url)
    if host in HF_HOSTS:
        found = _HF_FILE.match(parse.urlsplit(url).path)
        if found:
            return f"https://huggingface.co/{found.group('repo')}/resolve/{found.group('rev')}/{found.group('path')}"
        return url
    if host in CIVITAI_HOSTS and not parse.urlsplit(url).path.startswith("/api/download/"):
        return link_for(url, locale, folders).url
    if host in MODELSCOPE_HOSTS:
        target = _ms_link(url, locale)
        if target.path:
            return _ms_resolve_url(target.site, target.repo, target.revision or "master", target.path)
        return link_for(url, locale, folders).url
    return url


def provenance_of(url: str, locale: str) -> dict[str, Any]:
    """下载的这个链接是哪个站上的哪一页(经 Mosael 下载时记下,见 provenance):HuggingFace 的文件页、Civitai 的版本页
    (连着那个版本的信息)、ModelScope 的文件页。别的直链只记站点,不记页 —— 下载地址不是介绍页。

    尽力而为:问 Civitai 失败(断网、限流)不该挡住下载,那时只记站点。"""
    import civitai

    url = canonical_url(url)
    host = _host(url)
    if host in HF_HOSTS:
        found = _HF_FILE.match(parse.urlsplit(url).path)
        if found:
            return {"site": "huggingface", "page": f"https://huggingface.co/{found.group('repo')}/blob/{found.group('rev')}/"
                                                   f"{found.group('path')}"}
        return {"site": "huggingface"}
    if host in CIVITAI_HOSTS:
        version_id = civitai.version_id_of(url)
        try:
            info = civitai.version(version_id, locale) if version_id else None
        except (ComfyError, OSError):
            info = None
        return {"site": "civitai", "page": info["page"], "civitai": info} if info else {"site": "civitai"}
    if host in MODELSCOPE_HOSTS:
        try:
            target = _ms_link(url, locale)
        except ComfyError:
            return {"site": "modelscope"}
        base = f"https://{target.site}/models/{parse.quote(target.repo)}"
        if target.path:
            return {"site": "modelscope", "page": f"{base}/file/view/{parse.quote(target.revision or 'master', safe='')}/"
                                                  f"{parse.quote(target.path)}"}
        return {"site": "modelscope", "page": base}
    return {"site": "direct"}


def resolve(payload: dict[str, Any], comfy: Comfy, locale: str) -> dict[str, Any]:
    url = str(payload.get("url") or "").strip()
    info = folder_info(comfy) or {}
    folders = set(info)
    link = link_for(url, locale, folders)
    if not link.filename:
        raise ComfyError(say(locale, "从这个链接看不出文件名,下不了", "Can't tell the file name from this link"))
    # 同名的在不在:界面据此要求换名(不撞名的建议由界面按同一个规矩算 —— 用户可能改了目录,建议得跟着那个目录)
    exists = bool(link.folder) and norm(link.filename) in names_in(comfy, link.folder)
    return {
        "source": link.source, "url": link.url, "page": link.page, "filename": link.filename, "size": link.size,
        "folder": link.folder, "family": link.family, "triggers": link.triggers or [], "title": link.title,
        "exists": exists, "note": link.note,
        # 下载时会不会带上那个站的令牌(填了 HuggingFace / Civitai / ModelScope 令牌、链接正是那个站的):经 ComfyUI-Manager
        # 下载时 Civitai 的令牌只能拼进下载地址、留在那台机器的任务记录里,另两个的带不过去 —— 界面据此提醒
        "uses_token": bool(token_for(link.url)),
    }
