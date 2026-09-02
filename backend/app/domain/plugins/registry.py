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
import zipfile
from pathlib import Path
from typing import Any

import httpx

from app.core.http_retry import RetryingClient
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import ManifestError, parse
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
    """
    if not url.startswith(("http://", "https://")):
        raise PluginDomainError("插件市场地址只能是 http/https")
    try:
        with RetryingClient(timeout=REGISTRY_TIMEOUT_SECONDS, follow_redirects=True) as client:
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        raise PluginDomainError(f"打不开插件市场:{exc}") from exc
    except ValueError as exc:
        raise PluginDomainError("插件市场返回的不是合法 JSON") from exc
    entries = payload.get("plugins") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise PluginDomainError("插件市场格式不对:应当是 {\"plugins\": [...]}")
    return [entry for entry in entries if isinstance(entry, dict) and entry.get("id")]


def _download(url: str) -> bytes:
    if not url.startswith(("http://", "https://")):
        raise PluginDomainError("插件下载地址只能是 http/https")
    written = bytearray()
    try:
        with RetryingClient(timeout=DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True) as client:
            with client.stream("GET", url) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes():
                    written.extend(chunk)
                    if len(written) > MAX_ARCHIVE_BYTES:
                        raise PluginDomainError("插件包超过大小上限")
    except httpx.HTTPError as exc:
        raise PluginDomainError(f"下载插件失败:{exc}") from exc
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
            raise PluginDomainError(f"插件包里有符号链接,拒绝安装:{info.filename}")
        destination = (root / info.filename).resolve()
        if destination != root and not str(destination).startswith(str(root) + "/"):
            raise PluginDomainError(f"插件包里有越界路径,拒绝安装:{info.filename}")
        total += info.file_size
        if total > MAX_UNPACKED_BYTES:
            raise PluginDomainError("插件包解压后超过大小上限")
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
        raise PluginDomainError(f"这个包里没有 {MANIFEST_NAME},不是一个插件")
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
        raise PluginDomainError("这不是一个合法的 zip 包") from exc
    except PluginDomainError:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    try:
        root = _manifest_root(workdir)
        raw = json.loads((root / MANIFEST_NAME).read_text(encoding="utf-8"))
        parse(raw, str(root))  # 只为校验:清单不合法的包直接挡在门外
    except (ManifestError, PluginDomainError, ValueError) as exc:
        shutil.rmtree(workdir, ignore_errors=True)
        raise PluginDomainError(f"插件清单不合法:{exc}") from exc
    return raw, root, workdir


def install_archive(data: bytes, plugins_dir: Path, *, overwrite: bool = False) -> dict[str, Any]:
    """把一个 zip 装进插件目录。返回它的清单。

    `overwrite=False` 时**不覆盖已装的同 id 包**。覆盖是一件要单独同意的事:那个目录里
    可能已经有用户填过的东西,而且新版本可能声明了完全不同的权限。
    """
    raw, root, workdir = inspect_archive(data)
    try:
        plugin_id = str(raw["id"])
        target = plugins_dir / plugin_id
        if target.exists() and not overwrite:
            raise PluginDomainError(f"「{raw.get('name') or plugin_id}」已经装过了 —— 要装新版本请选「更新」")
        plugins_dir.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(root), str(target))
        logger.info("装上插件 %s(%s)", plugin_id, raw.get("version"))
        return raw
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


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
    "fetch_index",
    "inspect_archive",
    "install_archive",
    "install_from_url",
    "preview_from_url",
]
