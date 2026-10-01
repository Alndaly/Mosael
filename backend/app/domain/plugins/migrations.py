"""插件清单的自动迁移落到磁盘上:插件目录里的老写法**改成**新写法、写回文件。

升级链本身(哪几步、当前版本)在 mosael_formats.plugin_manifest_upgrade —— 装包时解析插件包的地方
(plugin_archive)要跑同一串,这里只管落盘:找清单、备份、改名、写回。迁移完标 `manifest_version`,
下次扫描直接跳过。

**会改用户磁盘上的文件**。这是有意的:插件目录由这个应用管理,而"你的清单是老格式,请手动
改成这样"是一句没人愿意读的话。原文件先备份成 `<名字>.bak`。
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path

from mosael_formats.plugin_manifest import MANIFEST_FILENAME
from mosael_formats.plugin_manifest_upgrade import MANIFEST_VERSION, upgrade

logger = logging.getLogger(__name__)

#: 清单的规范文件名(清单格式的一部分,见 mosael_formats)。别的名字会在迁移时被改成它 ——
#: 一个目录一份清单,一个名字。
CANONICAL_FILENAME = MANIFEST_FILENAME

#: 迁移时会被认出来并改名的通用写法。
LEGACY_FILENAMES = ("plugin.json",)


def migrate_directory(directory: Path) -> Path | None:
    """把一个插件目录里的清单迁到当前版本,返回规范路径(没有清单则 None)。

    改名 + 改内容都在这里发生,而且都是原地的 —— 扫描之后,磁盘上就只剩新写法。
    """
    path = _find_manifest(directory)
    if path is None:
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return path  # 内容坏了交给 packages 报错,不在这里静默吞掉
    if not isinstance(raw, dict):
        return path

    changed = upgrade(raw)
    canonical = directory / CANONICAL_FILENAME
    if changed:
        _backup(path)
        canonical.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if path != canonical:
            path.unlink()
            logger.info("plugin manifest migrated: %s → %s", path.name, canonical.name)
        else:
            logger.info("plugin manifest migrated: %s", path)
    return canonical if changed else path


def _find_manifest(directory: Path) -> Path | None:
    for name in (CANONICAL_FILENAME, *LEGACY_FILENAMES):
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None


def _backup(path: Path) -> None:
    """迁移前留一份。改的是用户磁盘上的文件,而 JSON 里可能有手写的注释顺序、缩进偏好 ——
    我们只保证语义不丢,不保证字节不变。"""
    backup = path.with_suffix(path.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(path, backup)


__all__ = ["CANONICAL_FILENAME", "LEGACY_FILENAMES", "MANIFEST_VERSION", "migrate_directory", "upgrade"]
