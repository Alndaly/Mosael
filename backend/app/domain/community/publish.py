"""「发布到社区」:工作流和插件(ADR 0026 §4)。

**工作流**发的是本机「导出」得到的那同一份 `.mosael-workflow.json`(domain/workflows/file_export),
加上作者填的标题、简介、标签和一张封面(从素材库里挑)。发布即上架。第一次发 `POST /workflows`,
拿回的 slug 记在本机那条工作流上(`workflows.community_slug`),之后再发就是 `POST /workflows/{slug}/versions`
—— 同一个条目的新版本,不是一条新的。

**插件**发的是和发版时同一种 zip(插件目录的内容放在包根上,见 .github/workflows/release.yml 的
Package plugins):目录在 git 里时只打**受版本管理的文件**,不在 git 里就打整个目录;两种情况都去掉缓存、
编译产物、系统垃圾和一切看着像密钥的文件(`.env*`、私钥)。打好之后先用「从文件安装」那一套规则自己验一遍
(registry.read_manifest)—— 装不上的包不往外发。插件要先审核(会在别人的电脑上跑代码),所以回来的状态是
「审核中」。
"""

from __future__ import annotations

import fnmatch
import io
import json
import logging
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy.orm import Session

from app.core.child_process import run_logged
from app.db.models import Asset, PluginPackage, Workflow
from app.domain.community.accounts import CommunityClient
from app.domain.community.errors import CommunityError
from app.domain.community.transport import absolute
from app.domain.plugins import registry as market
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import PATH_KEY
from app.domain.workflows.file_export import WORKFLOW_FILE_SUFFIX, ascii_file_stem, export_payload
from app.media.paths import resolve_key

logger = logging.getLogger(__name__)

MAX_TITLE_CHARS = 120
MAX_SUMMARY_CHARS = 2000
MAX_TAGS = 8
MAX_TAG_CHARS = 32
#: 封面图最大多少。它是一张卡片上的图,不是原片。
MAX_COVER_BYTES = 10 * 1024 * 1024

#: 打插件包时整个跳过的目录。
EXCLUDED_DIRS = frozenset({
    "__pycache__", ".git", ".hg", ".svn", ".venv", "venv", "node_modules",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", ".idea", ".vscode",
})
#: 打插件包时跳过的文件(按文件名匹配,不分大小写)。缓存、系统垃圾,以及**任何看着像密钥的东西** ——
#: 作者的 `.env` 里是他自己的 API Key,一旦进了包,就到了每个装它的人手里。
EXCLUDED_FILES = (
    "*.pyc", "*.pyo", ".DS_Store", "Thumbs.db", "desktop.ini",
    ".env", ".env.*", "*.env", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*",
    ".netrc", ".npmrc", ".pypirc", "*.secret", "secrets.json", "credentials.json",
    # 本机改写清单时留的备份(ADR 0006:改用户磁盘上的文件先留 .bak)—— 那是这台机器的事,不是插件的一部分。
    "*.bak",
)


def _published(result: dict[str, Any], origin: str, kind: str, *, slug: str = "") -> dict[str, Any]:
    """社区的回包 → `{slug, url, version, status}`。

    新建(`POST /workflows`)回的是条目详情,这一次提交的审核状态在 `submission` 里;发新版本
    (`POST /{slug}/versions`)只回那一版 —— 不带 slug,用调用方手里那个。条目详情没有网页地址时按站点上
    `/{kind}/{slug}` 拼。
    """
    submission = result.get("submission") if isinstance(result.get("submission"), dict) else {}
    slug = str(result.get("slug") or slug or "")
    if not slug:
        raise CommunityError("communityErr_badResponse")
    return {
        "slug": slug,
        "url": absolute(origin, str(result.get("url") or f"/{kind}/{slug}")),
        "version": str(result.get("version") or submission.get("version") or ""),
        "status": str(result.get("status") or submission.get("status") or "published"),
    }


def _tags(tags: list[str]) -> list[str]:
    cleaned: list[str] = []
    for tag in tags:
        one = " ".join(str(tag).split())[:MAX_TAG_CHARS]
        if one and one not in cleaned:
            cleaned.append(one)
    return cleaned[:MAX_TAGS]


def _cover(db: Session, workspace_id: str, asset_id: str | None) -> tuple[str, bytes, str] | None:
    """封面:素材库里的一张图(这个工作区的、盘上有文件的)。"""
    if not asset_id:
        return None
    asset = db.get(Asset, asset_id)
    if asset is None or asset.workspace_id != workspace_id or asset.kind != "image" or not asset.file_key:
        raise CommunityError("communityErr_coverNotImage")
    path = resolve_key(asset.file_key)
    if not path.is_file():
        raise CommunityError("communityErr_coverMissing")
    if path.stat().st_size > MAX_COVER_BYTES:
        raise CommunityError("communityErr_coverTooLarge", limit=MAX_COVER_BYTES // (1024 * 1024))
    import mimetypes

    return path.name, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def publish_workflow(
    db: Session,
    *,
    workflow: Workflow,
    user_id: str,
    title: str,
    summary: str,
    tags: list[str],
    cover_asset_id: str | None,
) -> dict[str, Any]:
    """发一条工作流(第一次)或它的新版本(之后)。回 `{slug, url, version, status}`。"""
    client = CommunityClient.for_user(db, user_id)
    name = (title or "").strip()[:MAX_TITLE_CHARS] or workflow.name
    document = json.dumps(export_payload(workflow), ensure_ascii=False, indent=2).encode("utf-8")
    files: dict[str, tuple[str, bytes, str]] = {
        "file": (f"{ascii_file_stem(workflow.name)}{WORKFLOW_FILE_SUFFIX}", document, "application/json"),
    }
    cover = _cover(db, workflow.workspace_id, cover_asset_id)
    if cover is not None:
        files["cover"] = cover
    fields = {
        "title": name,
        "summary": (summary or "").strip()[:MAX_SUMMARY_CHARS],
        "tags": json.dumps(_tags(tags), ensure_ascii=False),
    }
    path = f"/workflows/{workflow.community_slug}/versions" if workflow.community_slug else "/workflows"
    result = _published(client.call("POST", path, data=fields, files=files), client.origin, "workflows",
                        slug=workflow.community_slug)
    workflow.community_slug = result["slug"]
    db.commit()
    return result


# --- 插件 -----------------------------------------------------------------


def _excluded(relative: PurePosixPath) -> bool:
    if any(part in EXCLUDED_DIRS for part in relative.parts[:-1]):
        return True
    name = relative.name.lower()
    return any(fnmatch.fnmatch(name, pattern.lower()) for pattern in EXCLUDED_FILES)


def _tracked_files(directory: Path) -> list[PurePosixPath] | None:
    """目录在 git 里:受版本管理的文件(相对这个目录)。不在 git 里(或没装 git):None。"""
    # 先看一眼有没有仓库,没有就不起 git —— 否则每发一次都在日志里留一条「not a git repository」。
    if not any((parent / ".git").exists() for parent in (directory, *directory.parents)):
        return None
    try:
        result = run_logged(
            ["git", "-C", str(directory), "ls-files", "-z", "--cached", "--", "."],
            what="列出插件的受管文件",
            capture_output=True,
            timeout=30,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    raw = result.stdout.decode("utf-8", "replace") if isinstance(result.stdout, bytes) else str(result.stdout)
    return [PurePosixPath(one) for one in raw.split("\0") if one]


def _all_files(directory: Path) -> list[PurePosixPath]:
    found: list[PurePosixPath] = []
    for path in sorted(directory.rglob("*")):
        if path.is_file() and not path.is_symlink():
            found.append(PurePosixPath(path.relative_to(directory).as_posix()))
    return found


def package_plugin(directory: Path) -> bytes:
    """把一个插件目录打成 zip(和发版的包同形:目录的内容在包根上)。"""
    tracked = _tracked_files(directory)
    # 在某个 git 仓库里、却一个受管文件都没有(家目录本身是个仓库这种):那不是「只打受管文件」的意思,按整个目录打。
    names = tracked if tracked else _all_files(directory)
    buffer = io.BytesIO()
    total = 0
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for relative in sorted(set(names)):
            if _excluded(relative):
                continue
            path = directory / Path(*relative.parts)
            # 符号链接不打:装的那一侧会整包拒掉(registry._safe_extract),而它指向的东西不在包里。
            if path.is_symlink() or not path.is_file():
                continue
            total += path.stat().st_size
            if total > market.MAX_UNPACKED_BYTES:
                raise CommunityError("communityErr_pluginTooLarge")
            archive.write(path, relative.as_posix())
    data = buffer.getvalue()
    if len(data) > market.MAX_ARCHIVE_BYTES:
        raise CommunityError("communityErr_pluginTooLarge")
    return data


def plugin_directory(package: PluginPackage) -> Path:
    raw = (package.manifest or {}).get(PATH_KEY)
    directory = Path(str(raw)) if raw else None
    if directory is None or not directory.is_dir():
        raise CommunityError("communityErr_pluginDirMissing")
    return directory


def publish_plugin(db: Session, *, package: PluginPackage, user_id: str, summary: str, tags: list[str]) -> dict[str, Any]:
    """打包、自检、上传。回 `{slug, url, version, status}`,status 通常是 `pending`(审核中)。"""
    from app.domain.plugins import bundled

    if bundled.is_bundled(package.id):
        raise CommunityError("communityErr_pluginBundled")
    client = CommunityClient.for_user(db, user_id)
    data = package_plugin(plugin_directory(package))
    try:
        market.read_manifest(data)
    except PluginDomainError as exc:
        # 自己打的包自己都装不上:说清原因(清单哪里不对),别让它到审核队列里才被拒。
        raise CommunityError("communityErr_pluginInvalid", detail=str(exc)) from exc
    fields = {"summary": (summary or "").strip()[:MAX_SUMMARY_CHARS], "tags": json.dumps(_tags(tags), ensure_ascii=False)}
    files = {"file": (f"{package.id}.zip", data, "application/zip")}
    result = client.call("POST", "/plugins", data=fields, files=files)
    return _published(result, client.origin, "plugins")
