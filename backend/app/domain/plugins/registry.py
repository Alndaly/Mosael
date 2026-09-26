"""插件市场:一份可浏览的索引,以及「从一个地址装下来」。

此前装插件的唯一办法是**手动把文件夹丢进插件目录再点扫描**。这对写插件的人没问题,
对用它的人是道墙 —— 而插件的价值恰恰在于用的人比写的人多得多。

## 索引就是一份 JSON

    {"plugins": [{"id": "...", "name": "...", "description": "...",
                  "version": "...", "author": "...", "homepage": "...",
                  "download": "https://.../x.zip", "permissions": ["network:x"]}]}

**地址可配置**,默认指向本项目的那一份。格式是普通 JSON、没有签名也没有账号 ——
谁都能自己架一个,包括公司内网。这是有意的:插件系统的价值在于长出来的东西,
而一个必须经过我们审核的市场长不出多少东西。

代价是**索引不是信任背书**。所以真正的防线不在这里,而在装的那一刻:装什么、它声明了
哪些权限,都摊开给用户看过才动手(见 install_from_url 与前端的安装确认)。

## 装的时候在防什么

装插件 = 在用户机器上放一份**会被执行**的代码。这里挡住的是:压缩包里的路径穿越
(`../../.ssh/authorized_keys`)、解压炸弹、没有清单的垃圾包、以及悄悄覆盖掉一个已经装好
并且已经填了凭据的包。挡不住的是「这个作者是不是好人」—— 那件事只能由用户看着权限清单
自己决定,所以那份清单必须在装之前就看得见。
"""

from __future__ import annotations

import io
import json
import logging
import shutil
import tempfile
import threading
import uuid
import zipfile
from pathlib import Path
from typing import Any

import httpx

from app.core.http_retry import RetryingClient
from app.domain.effects import plugin_tool_effects
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import Manifest, ManifestError, parse
from app.domain.plugins.migrations import CANONICAL_FILENAME as MANIFEST_NAME

logger = logging.getLogger(__name__)

#: 压缩包最大多少。插件是脚本和清单,正常几十 KB 到几 MB。给上限是挡解压炸弹 ——
#: 一个 1MB 的 zip 能解出几十 GB。
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_UNPACKED_BYTES = 256 * 1024 * 1024

DOWNLOAD_TIMEOUT_SECONDS = 60.0
REGISTRY_TIMEOUT_SECONDS = 15.0


def fetch_index(url: str) -> list[dict[str, Any]]:
    """拉一份索引。拉不到就是拉不到 —— 不缓存、不兜底到一份内置清单。

    兜底会让「市场里怎么少了一个」变成一个查不清的问题:用户看到的到底是这一刻的索引,
    还是某次成功之后留下的旧副本?

    拉不到时市场里照样列着随应用内置的插件(见 routes/plugins.browse_market)—— 那不是远端的
    兜底副本,而是本机装着的事实;拉不到的原因照样交给界面说出来。
    """
    if not url.startswith(("http://", "https://")):
        raise PluginDomainError("pluginErr_marketBadScheme")
    try:
        # 市场列表是一段前台交互,不能继承 AI 供应商那套多次退避重试。远端挂掉时应在一次
        # 明确的超时后把错误交给界面,否则 15 秒会被放大数倍,用户只会一直看到骨架屏。
        with RetryingClient(
            timeout=REGISTRY_TIMEOUT_SECONDS,
            follow_redirects=True,
            max_retries=0,
        ) as client:
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise PluginDomainError("pluginErr_marketUnreachable", detail=str(exc)) from exc
    except ValueError as exc:
        raise PluginDomainError("pluginErr_marketNotJson") from exc
    entries = payload.get("plugins") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise PluginDomainError("pluginErr_marketBadShape", example='{"plugins": [...]}')
    return [entry for entry in entries if isinstance(entry, dict) and entry.get("id")]


#: 仓库里插件目录的网页地址。条目没写主页时退到它 —— 至少还能读到源码和 README。
#: 与 scripts/sync-plugin-registry.py 同一条规则(那边生成官网上的索引,这边补本机内置的条目)。
REPO_PLUGINS_URL = "https://github.com/Alndaly/Mosael/tree/main/plugins"


def _market_effects(manifest: Manifest, tool: dict[str, Any]) -> str:
    """市场里一个声明过的工具的后果。和装上之后(plugins.tools.all_tools)同一个算法 —— 覆盖 > 声明 > 包缺省。"""
    override = manifest.overrides.get(str(tool["name"]))
    return plugin_tool_effects(
        read_only=bool((override and override.read_only) or tool.get("read_only") is True),
        declared=(override.effects if override and override.effects else None) or tool.get("effects"),
        default=manifest.default_effects or None,
    )


def bundled_entry(manifest: Manifest, folder: str) -> dict[str, Any]:
    """随应用内置的插件在市场里的那一条,**由本机那份清单生成**,形状与远端索引的条目一样。

    和 scripts/sync-plugin-registry.py 给内置插件生成的条目一一对应:`bundled` 为真、没有下载
    地址(它跟着应用走,不从市场装)。取本机清单而不是远端那条,是因为远端可能更旧、可能拉不到,
    而这台机器上装着的是哪一版只有本机知道。
    """
    return {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "description": (manifest.skills[0].get("description") if manifest.skills else "") or "",
        "author": manifest.author.name,
        "author_url": manifest.author.url,
        "docs": manifest.docs,
        "homepage": manifest.homepage or f"{REPO_PLUGINS_URL}/bundled/{folder}",
        "download": "",
        "permissions": list(manifest.permissions),
        "runtime": manifest.runtime.kind,
        "provides": list(manifest.provides),
        "tools": [
            {
                "name": str(tool["name"]),
                "label": tool.get("label") or "",
                "description": tool.get("description") or "",
                # 和 scripts/sync-plugin-registry.py 同一个算法(domain/effects):装之前就看得到哪些工具会先问你。
                "effects": _market_effects(manifest, tool),
            }
            for tool in manifest.declared_tools
        ],
        "bundled": True,
    }


def _download(url: str) -> bytes:
    if not url.startswith(("http://", "https://")):
        raise PluginDomainError("pluginErr_downloadBadScheme")
    written = bytearray()
    try:
        with RetryingClient(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    written.extend(chunk)
                    if len(written) > MAX_ARCHIVE_BYTES:
                        raise PluginDomainError("pluginErr_archiveTooLarge")
    except httpx.HTTPError as exc:
        raise PluginDomainError("pluginErr_downloadFailed", detail=str(exc)) from exc
    return bytes(written)


def _safe_extract(archive: zipfile.ZipFile, target: Path) -> None:
    """解压,**逐条查落点**。

    zip 里的路径是压缩包作者写的字符串,可以是 `../../.ssh/authorized_keys`,也可以是一条
    指向别处的符号链接。Python 的 extractall 自 3.6 起会规范化 `..`,但不拦符号链接,
    也不拦解压炸弹 —— 这两样在这里显式拦。
    """
    total = 0
    root = target.resolve()
    for info in archive.infolist():
        # 符号链接:高 16 位是 st_mode,0o120000 是 S_IFLNK。
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise PluginDomainError("pluginErr_archiveSymlink", name=info.filename)
        destination = (root / info.filename).resolve()
        # 按路径的**段**比,不按字符串前缀比:此前拼的是 `root + "/"`,Windows 上的路径分隔符是 `\\`,
        # 于是每一条都被当成越界 —— Windows 上从市场一个插件也装不上。
        if not destination.is_relative_to(root):
            raise PluginDomainError("pluginErr_archivePathEscape", name=info.filename)
        total += info.file_size
        if total > MAX_UNPACKED_BYTES:
            raise PluginDomainError("pluginErr_archiveUnpackedTooLarge")
    archive.extractall(target)


def _manifest_root(unpacked: Path) -> Path:
    """找到清单所在的那一层。

    从 GitHub 下下来的 zip 外面总套一层 `repo-main/`,而清单在里面。认死最外层的话,
    从 GitHub 下的包一个都装不上 —— 而那正是最常见的来源。
    """
    direct = unpacked / MANIFEST_NAME
    if direct.is_file():
        return unpacked
    candidates = sorted(unpacked.rglob(MANIFEST_NAME), key=lambda p: len(p.parts))
    if not candidates:
        raise PluginDomainError("pluginErr_archiveNoManifest", manifest=MANIFEST_NAME)
    return candidates[0].parent


def inspect_archive(data: bytes) -> tuple[dict[str, Any], Path, Path]:
    """解到临时目录并读出清单。返回 (清单, 清单所在目录, 临时根目录)。

    **先看清楚再落地**:清单不合法、或者根本没有清单的包,不该在插件目录里留下任何东西。
    调用方负责删掉临时根目录。
    """
    workdir = Path(tempfile.mkdtemp(prefix="mosael-plugin-install-"))
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            _safe_extract(archive, workdir)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise PluginDomainError("pluginErr_archiveNotZip") from exc
    except PluginDomainError:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    try:
        root = _manifest_root(workdir)
        raw = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
        parse(raw, str(root))  # 只为校验:清单不合法的包直接挡在门外
    except (ManifestError, PluginDomainError, ValueError) as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise PluginDomainError("pluginErr_manifestInvalid", detail=str(exc)) from exc
    return raw, root, workdir


#: 同一时刻只换一个插件目录。两次安装同一个 id 撞在一起时,先到的装完、后到的按「已经装过」处理,
#: 而不是两边都判「还没装」、一个把目录挪进另一个里面去。
_INSTALL_LOCK = threading.Lock()


def install_archive(data: bytes, plugins_dir: Path, *, overwrite: bool = False) -> dict[str, Any]:
    """把一个 zip 装进插件目录。返回它的清单。

    `overwrite=False` 时**不覆盖已装的同 id 包**。覆盖是一件要单独同意的事:那个目录里
    可能已经有用户填过的东西,而且新版本可能声明了完全不同的权限。

    **随应用发的插件不能被市场上的包顶替**(见 bundled):它们和插件目录里别的包住在一起,此前一个
    id 写成 `dev.mosael.comfyui` 的第三方包选「更新」就能把随包的 ComfyUI 整个换成自己的代码。

    **换目录是原子的**:先把新版本完整地放到插件目录里一个隐藏的暂存目录(同一个文件系统),再用两次
    rename 换上去。此前是先 rmtree 旧目录再从临时目录 move 过来 —— 临时目录和插件目录不在同一个
    文件系统时 move 是逐个文件拷贝,拷到一半失败,留下的是半个新版本、旧版本已经没了。
    """
    from app.domain.plugins import bundled

    raw, root, workdir = inspect_archive(data)
    staging: Path | None = None
    try:
        plugin_id = str(raw["id"]).strip()  # 形状在 parse 里查过(manifest.PLUGIN_ID_RE)
        name = raw.get("name") or plugin_id
        if bundled.is_bundled(plugin_id):
            raise PluginDomainError("pluginErr_bundledCannotReplace", name=name)
        target = plugins_dir / plugin_id
        if target.exists() and not overwrite:
            raise PluginDomainError("pluginErr_alreadyInstalled", name=name)
        plugins_dir.mkdir(parents=True, exist_ok=True)
        staging = plugins_dir / f".{plugin_id}.installing-{uuid.uuid4().hex[:8]}"
        shutil.move(str(root), str(staging))
        with _INSTALL_LOCK:
            _swap_in(staging, target, overwrite=overwrite, name=name)
        staging = None
        logger.info("装上插件 %s(%s)", plugin_id, raw.get("version"))
        return raw
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
        if staging is not None:
            shutil.rmtree(staging, ignore_errors=True)


def _swap_in(staging: Path, target: Path, *, overwrite: bool, name: str) -> None:
    """把暂存目录换成 `target`。换失败时旧版本原样留着。"""
    if not target.exists():
        staging.rename(target)
        return
    if not overwrite:
        raise PluginDomainError("pluginErr_alreadyInstalled", name=name)
    retired = target.with_name(f".{target.name}.replaced-{uuid.uuid4().hex[:8]}")
    target.rename(retired)
    try:
        staging.rename(target)
    except OSError:
        retired.rename(target)
        raise
    shutil.rmtree(retired, ignore_errors=True)


def install_from_url(url: str, plugins_dir: Path, *, overwrite: bool = False) -> dict[str, Any]:
    return install_archive(_download(url), plugins_dir, overwrite=overwrite)


def preview_from_url(url: str) -> dict[str, Any]:
    """只看不装:下下来读一遍清单就扔。

    给「装之前先让用户看看它要什么权限」用 —— 权限清单写在清单里,而清单在包里面,
    不下下来看不到。
    """
    raw, _, workdir = inspect_archive(_download(url))
    shutil.rmtree(workdir, ignore_errors=True)
    return raw


__all__ = [
    "MAX_ARCHIVE_BYTES",
    "MAX_UNPACKED_BYTES",
    "REPO_PLUGINS_URL",
    "bundled_entry",
    "fetch_index",
    "inspect_archive",
    "install_archive",
    "install_from_url",
    "preview_from_url",
]
