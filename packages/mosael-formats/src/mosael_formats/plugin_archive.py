"""插件包(zip)的安全检查与读取。桌面端「从文件安装 / 从市场装」和社区上架过的是这同一份。

装插件 = 在用户机器上放一份**会被执行**的代码。这里挡住的是:压缩包里的路径穿越
(`../../.ssh/authorized_keys`)、符号链接、解压炸弹,以及没有清单或清单不合法的包。挡不住的是
「这个作者是不是好人」—— 那件事由用户看着权限清单自己决定(桌面端),或者由审核的人决定(社区)。

**先在内存里看清楚,再落地。** `read_plugin_archive` 不碰磁盘:它把每一条成员查一遍、找到清单、
解析并校验它、列出文件与哈希。要落地的一方(桌面端)再用 `safe_extract` 解到自己的目录里,
那里逐条再查一次 —— 解压这一步本身不该信任任何一次之前的检查。
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from mosael_formats.i18n import FormatError
from mosael_formats.plugin_manifest import MANIFEST_FILENAME, Manifest, ManifestError, parse

#: 压缩包最大多少。插件是脚本和清单,正常几十 KB 到几 MB。给上限是挡解压炸弹 ——
#: 一个 1MB 的 zip 能解出几十 GB。
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_UNPACKED_BYTES = 256 * 1024 * 1024

_DRIVE = re.compile(r"^[A-Za-z]:")


class ArchiveError(FormatError):
    """插件包本身不合格(不是 zip、太大、有符号链接、有越界路径、没有清单、清单不合法)。"""


@dataclass(frozen=True)
class ArchiveFile:
    """包里的一个文件,路径相对于清单所在的那一层。"""

    path: str
    size: int
    sha256: str


@dataclass(frozen=True)
class PluginArchive:
    #: 清单原文(解析前的字典)。
    raw: dict[str, Any]
    #: 解析、校验过的清单。
    manifest: Manifest
    #: 清单在 zip 里的成员名(`repo-main/mosael.plugin.json` 之类)。
    manifest_member: str
    #: 清单所在的那一层,相对 zip 根;在最外层时是空串。
    root: str
    #: 那一层之下的全部文件,按路径排序。
    files: list[ArchiveFile] = field(default_factory=list)


def is_symlink(info: zipfile.ZipInfo) -> bool:
    """符号链接:高 16 位是 st_mode,0o120000 是 S_IFLNK。"""
    return (info.external_attr >> 16) & 0o170000 == 0o120000


def escapes_root(name: str) -> bool:
    """这个成员名解出来会不会落到解压目录**之外**。

    按路径的**段**判,不按字符串前缀判,也不依赖磁盘:`/` 和 `\\` 都当分隔符(Windows 上两个都是),
    绝对路径和盘符一律算越界,`..` 退到根之上算越界。一条名字在哪个平台上解都得在里面。
    """
    normalized = name.replace("\\", "/")
    if normalized.startswith("/") or _DRIVE.match(normalized):
        return True
    depth = 0
    for segment in normalized.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            depth -= 1
            if depth < 0:
                return True
        else:
            depth += 1
    return False


def open_archive(data: bytes, *, max_archive_bytes: int | None = MAX_ARCHIVE_BYTES) -> zipfile.ZipFile:
    """把字节当 zip 打开。太大、不是 zip 都在这里说。调用方负责关掉它。"""
    if max_archive_bytes is not None and len(data) > max_archive_bytes:
        raise ArchiveError("pluginErr_archiveTooLarge")
    try:
        return zipfile.ZipFile(io.BytesIO(data))
    except (zipfile.BadZipFile, ValueError) as exc:
        raise ArchiveError("pluginErr_archiveNotZip") from exc


def check_members(
    archive: zipfile.ZipFile, *, max_unpacked_bytes: int = MAX_UNPACKED_BYTES, max_files: int | None = None
) -> list[zipfile.ZipInfo]:
    """逐条查成员:没有符号链接、没有越界路径、声明的解压后总大小不超限。返回全部成员。

    上限查的是**声明的**解压后大小,在解之前 —— 等解出来再数就晚了。声明和实际不符的,zipfile 在
    读的时候会因为 CRC / 长度对不上而报错,不会悄悄多写。
    """
    members = archive.infolist()
    if max_files is not None and len(members) > max_files:
        raise ArchiveError("pluginErr_archiveTooManyFiles", limit=max_files)
    total = 0
    for info in members:
        if is_symlink(info):
            raise ArchiveError("pluginErr_archiveSymlink", name=info.filename)
        if escapes_root(info.filename):
            raise ArchiveError("pluginErr_archivePathEscape", name=info.filename)
        total += info.file_size
        if total > max_unpacked_bytes:
            raise ArchiveError("pluginErr_archiveUnpackedTooLarge")
    return members


def manifest_member(names: list[str]) -> str:
    """找到清单那一条:离根最近的那份(同深度按名字排)。

    从 GitHub 下下来的 zip 外面总套一层 `repo-main/`,而清单在里面。认死最外层的话,
    从 GitHub 下的包一个都装不上 —— 而那正是最常见的来源。
    """
    candidates = [
        name for name in names
        if not name.endswith("/") and PurePosixPath(name.replace("\\", "/")).name == MANIFEST_FILENAME
    ]
    if not candidates:
        raise ArchiveError("pluginErr_archiveNoManifest", manifest=MANIFEST_FILENAME)
    return min(candidates, key=lambda name: (len(PurePosixPath(name.replace("\\", "/")).parts), name))


def read_plugin_archive(
    data: bytes,
    *,
    max_archive_bytes: int | None = MAX_ARCHIVE_BYTES,
    max_unpacked_bytes: int = MAX_UNPACKED_BYTES,
    max_files: int | None = None,
) -> PluginArchive:
    """在内存里把一个插件包看清楚:成员安全、清单存在、清单合法。不合格就抛 ArchiveError。"""
    with open_archive(data, max_archive_bytes=max_archive_bytes) as archive:
        members = check_members(archive, max_unpacked_bytes=max_unpacked_bytes, max_files=max_files)
        member = manifest_member([info.filename for info in members])
        root = str(PurePosixPath(member.replace("\\", "/")).parent)
        root = "" if root == "." else root
        try:
            raw = json.loads(archive.read(member).decode("utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("manifest is not a JSON object")
            manifest = parse(raw, member)
        except (ManifestError, ValueError, UnicodeDecodeError) as exc:
            raise ArchiveError("pluginErr_manifestInvalid", detail=str(exc)) from exc
        except (zipfile.BadZipFile, OSError) as exc:
            raise ArchiveError("pluginErr_archiveNotZip") from exc
        files: list[ArchiveFile] = []
        prefix = f"{root}/" if root else ""
        for info in members:
            name = info.filename.replace("\\", "/")
            if info.is_dir() or not name.startswith(prefix):
                continue
            try:
                digest = hashlib.sha256(archive.read(info)).hexdigest()
            except (zipfile.BadZipFile, OSError) as exc:
                raise ArchiveError("pluginErr_archiveNotZip") from exc
            files.append(ArchiveFile(path=name[len(prefix):], size=info.file_size, sha256=digest))
    files.sort(key=lambda one: one.path)
    return PluginArchive(raw=raw, manifest=manifest, manifest_member=member, root=root, files=files)


def safe_extract(archive: zipfile.ZipFile, target: Path, *, max_unpacked_bytes: int = MAX_UNPACKED_BYTES) -> None:
    """解压,**逐条查落点**。

    Python 的 extractall 自 3.6 起会规范化 `..`,但不拦符号链接,也不拦解压炸弹 —— 这两样在
    check_members 里显式拦。
    """
    check_members(archive, max_unpacked_bytes=max_unpacked_bytes)
    archive.extractall(target)


__all__ = [
    "ArchiveError",
    "ArchiveFile",
    "MAX_ARCHIVE_BYTES",
    "MAX_UNPACKED_BYTES",
    "PluginArchive",
    "check_members",
    "escapes_root",
    "is_symlink",
    "manifest_member",
    "open_archive",
    "read_plugin_archive",
    "safe_extract",
]
