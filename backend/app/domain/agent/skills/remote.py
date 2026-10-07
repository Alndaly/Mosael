"""从一个链接取回技能(智能体的 import_skill,ADR 0043):`.zip`,或 GitHub 上的一个技能文件夹。

取回来的东西和设置页上传的走**同一条**读法(`mosael_formats.agent_skill` 的 read_skill_archive / bundles_from_files):
同一套大小、个数、路径的上限,同样丢掉系统垃圾、拒绝符号链接。这里只管「怎么把字节拿回来」。

- **出口走 core/outbound_guard**:地址是模型写的,只许去公网(部署允许名单除外),每一跳重定向重新判;代理照
  应用的网络设置(进程环境,见 domain/network)。每次请求都给上限,边收边数 —— 对面说的大小可能是假的。
- **GitHub 文件夹用内容接口**(`api.github.com/repos/…/contents/…`)逐层列,文件从 `download_url`
  (raw.githubusercontent.com)取:只拿那一个文件夹,不把整个仓库打包下回来。列表里先看大小,超了的不下。
  `tree/<分支>/<路径>` 里的分支只认第一段(`feature/x` 这种带斜杠的分支名认不出,给 .zip 链接)。
- 只认 https:http 链接中途能被改包,而导进来的是要给智能体照做的文字。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.parse import quote, unquote, urlsplit

import httpx

from app.core import outbound_guard
from app.domain.agent.skills.catalog import SkillDomainError
from mosael_formats.agent_skill import (
    JUNK_DIRS,
    MAX_ARCHIVE_UNPACKED_BYTES,
    MAX_FILE_BYTES,
    MAX_SKILL_FILES,
    MAX_SKILLS_PER_IMPORT,
    SKILL_FILENAME,
)

_TIMEOUT = 30.0
_UA = "Mosael-skill-import"
#: 一个 GitHub 文件夹最多往下列几层目录(每层一次接口调用;没带令牌时 GitHub 一小时只给 60 次)。
MAX_LISTED_DIRS = 40
#: 一次最多收几个文件:和压缩包同一个数(一次最多导 20 个技能,每个最多 200 个文件)。
MAX_FETCHED_FILES = MAX_SKILL_FILES * MAX_SKILLS_PER_IMPORT


@dataclass(frozen=True)
class Fetched:
    """取回来的东西:要么一个压缩包,要么一堆文件(相对路径 → 内容,最外层是那个文件夹的名字)。"""

    source_name: str
    archive: bytes | None = None
    files: dict[str, bytes] | None = None


@dataclass(frozen=True)
class _GitHubFolder:
    owner: str
    repo: str
    ref: str
    path: str


def fetch(url: str) -> Fetched:
    """链接 → 取回来的东西。认不出的链接、取不回来、太大,都抛 SkillDomainError(带一句模型读得懂的话)。"""
    text = str(url or "").strip()
    parts = urlsplit(text)
    if parts.scheme != "https" or not parts.hostname:
        raise SkillDomainError("skillErr_importUrl", url=text[:200])
    source_name = f"{parts.hostname}{parts.path}".rstrip("/")[:255]
    if parts.path.lower().endswith(".zip"):
        return Fetched(source_name=source_name, archive=_get(text, limit=MAX_ARCHIVE_UNPACKED_BYTES).content)
    folder = _github_folder(parts.hostname, parts.path)
    if folder is None:
        raise SkillDomainError("skillErr_importUrl", url=text[:200])
    return Fetched(source_name=source_name, files=_github_files(folder))


def _github_folder(host: str, path: str) -> _GitHubFolder | None:
    """`github.com/<作者>/<仓库>[/tree|blob/<分支>/<路径>]` → 要取的那个文件夹。指着 SKILL.md 的 blob 链接取它所在的文件夹。"""
    if host.lower() not in ("github.com", "www.github.com"):
        return None
    segments = [unquote(one) for one in path.split("/") if one]
    if len(segments) < 2:
        return None
    owner, repo = segments[0], segments[1].removesuffix(".git")
    rest = segments[2:]
    if not rest:
        return _GitHubFolder(owner, repo, "", "")
    if rest[0] not in ("tree", "blob") or len(rest) < 2:
        return None
    ref, inner = rest[1], rest[2:]
    if rest[0] == "blob":
        if not inner or inner[-1] != SKILL_FILENAME:
            return None
        inner = inner[:-1]
    if any(one in (".", "..") for one in inner):
        return None
    return _GitHubFolder(owner, repo, ref, "/".join(inner))


def _github_files(folder: _GitHubFolder) -> dict[str, bytes]:
    """逐层列出那个文件夹,把文件取回来。路径以文件夹自己的名字开头(仓库根就用仓库名)——
    导入那一步按「SKILL.md 在哪一层」认技能,外面这一层名字就是审阅时显示的「原来的文件夹」。"""
    top = folder.path.rsplit("/", 1)[-1] if folder.path else folder.repo
    prefix = f"{folder.path}/" if folder.path else ""
    pending = [folder.path]
    listed = 0
    wanted: list[tuple[str, str]] = []
    total = 0
    while pending:
        current = pending.pop(0)
        listed += 1
        if listed > MAX_LISTED_DIRS:
            raise SkillDomainError("skillErr_importTooBig", limit=MAX_LISTED_DIRS)
        for entry in _list(folder, current):
            kind = str(entry.get("type") or "")
            path = str(entry.get("path") or "")
            relative = path[len(prefix):] if path.startswith(prefix) else path
            name = relative.rsplit("/", 1)[-1]
            if kind == "dir":
                if name not in JUNK_DIRS:
                    pending.append(path)
                continue
            if kind != "file":
                # 符号链接、子模块:和压缩包里的符号链接一样拒(ADR 0040 §6),不跟着它去别处取。
                raise SkillDomainError("skillErr_symlink", path=relative[:120])
            size = int(entry.get("size") or 0)
            if size > MAX_FILE_BYTES:
                raise SkillDomainError("skillErr_fileTooLarge", path=relative[:120], limit=MAX_FILE_BYTES // (1024 * 1024))
            total += size
            if total > MAX_ARCHIVE_UNPACKED_BYTES:
                raise SkillDomainError("skillErr_archiveTooLarge", limit=MAX_ARCHIVE_UNPACKED_BYTES // (1024 * 1024))
            if len(wanted) >= MAX_FETCHED_FILES:
                raise SkillDomainError("skillErr_tooManyFiles", limit=MAX_SKILL_FILES)
            download = str(entry.get("download_url") or "")
            if not download:
                raise SkillDomainError("skillErr_importFetchFailed", detail=relative[:120])
            wanted.append((f"{top}/{relative}", download))
    return {path: _get(download, limit=MAX_FILE_BYTES).content for path, download in wanted}


def _list(folder: _GitHubFolder, path: str) -> list[dict]:
    url = f"https://api.github.com/repos/{quote(folder.owner)}/{quote(folder.repo)}/contents/{quote(path)}"
    if folder.ref:
        url += f"?ref={quote(folder.ref, safe='')}"
    response = _get(url, limit=MAX_ARCHIVE_UNPACKED_BYTES, accept="application/vnd.github+json")
    try:
        listing = json.loads(response.content)
    except ValueError as exc:
        raise SkillDomainError("skillErr_importFetchFailed", detail=url[:200]) from exc
    if not isinstance(listing, list):
        # 指着的是一个文件,不是文件夹。
        raise SkillDomainError("skillErr_importUrl", url=url[:200])
    return [one for one in listing if isinstance(one, dict)]


def _get(url: str, *, limit: int, accept: str = "*/*") -> httpx.Response:
    try:
        exchange = outbound_guard.send(
            "GET", url, headers={"User-Agent": _UA, "Accept": accept}, timeout=_TIMEOUT, follow_redirects=True,
            max_bytes=limit,
        )
    except (outbound_guard.OutboundBlocked, outbound_guard.ResponseTooLarge) as exc:
        raise SkillDomainError.relay(exc) from exc
    except httpx.HTTPError as exc:
        raise SkillDomainError("skillErr_importFetchFailed", detail=str(exc)[:200]) from exc
    response = exchange.response
    if response.status_code == 404:
        raise SkillDomainError("skillErr_importNotFound", url=url[:200])
    if response.status_code in (403, 429) and "github.com" in url:
        raise SkillDomainError("skillErr_importRateLimited")
    if response.status_code >= 400:
        raise SkillDomainError("skillErr_importFetchFailed", detail=f"HTTP {response.status_code}")
    return response


__all__ = ["Fetched", "MAX_LISTED_DIRS", "fetch"]
