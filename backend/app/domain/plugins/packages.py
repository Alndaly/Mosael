"""插件**包**:磁盘上的目录 ↔ 数据库里的记录。

包没有「启用」状态,也没有凭据 —— 那些属于实例(instances.py)。这里只管三件事:
扫出来、装不下的清掉、卸载时连目录一起删。
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PluginInstance, PluginPackage
from app.domain.plugins.errors import PluginDomainError
from app.domain.plugins.manifest import PATH_KEY, ManifestError, parse
from app.domain.plugins.migrations import CANONICAL_FILENAME, LEGACY_FILENAMES, migrate_directory
from app.domain.plugins.runtime import data_dir_for

logger = logging.getLogger(__name__)

#: 老写法的清单在扫描时被**改写成**新写法(见 migrations.py),所以这里只认规范名。
#: 兼容负担在升级那一刻付一次,读取代码里不留分支。
MANIFEST_FILENAMES = (CANONICAL_FILENAME, *LEGACY_FILENAMES)

def scan(db: Session, plugins_dir: Path) -> list[PluginPackage]:
    """扫描插件目录。新包只登记不启用;目录已经不在的包连同它的实例一起清掉。

    **无配置的包自动建一个默认实例**:text-toolkit 这种装上就能用的东西,不该逼用户先去
    "新建一个连接"。有配置的包留给用户自己建 —— 因为建之前我们不知道它该叫什么名字。
    """
    plugins_dir.mkdir(parents=True, exist_ok=True)
    scanned: list[PluginPackage] = []
    for manifest_path in _iter_manifest_paths(plugins_dir):
        scanned.append(register(db, manifest_path))
    _prune(db, plugins_dir)
    db.commit()
    for package in scanned:
        db.refresh(package)
    return scanned


def register(db: Session, manifest_path: Path) -> PluginPackage:
    """登记**一个**插件目录(清单在 `manifest_path`)。扫描逐个走它;随应用发的内置插件
    (见 bundled)只登记自己那几个 —— 不该因为插件目录里另一个第三方包的清单写坏了而装不上。
    """
    # 老写法在这里就地改成新写法(改名 + 改内容),之后的代码只认一种形状。
    manifest_path = migrate_directory(manifest_path.parent) or manifest_path
    raw = _load(manifest_path)
    raw[PATH_KEY] = str(manifest_path.parent)
    try:
        manifest = parse(raw, str(manifest_path))
    except ManifestError as exc:
        raise PluginDomainError(str(exc)) from exc
    package = db.get(PluginPackage, manifest.id)
    if package is None:
        package = PluginPackage(id=manifest.id, name=manifest.name, version=manifest.version, manifest=raw)
        db.add(package)
        db.flush()
    else:
        package.name, package.version, package.manifest = manifest.name, manifest.version, raw
    return package


def uninstall(db: Session, package_id: str, plugins_dir: Path) -> None:
    """卸载:删目录 + 删记录(实例、凭据、授权、能力、调用记录随外键级联)。

    **必须连目录一起删**。只清记录的话,下一次扫描又把它装回来 —— 用户看到的是"我删了它
    怎么又回来了",而这个页面上没有任何东西能解释那件事。

    动手前认两件事:目录是 plugins_dir 的**直接子目录**,而且里面确实有一份清单文件。
    manifest 的 `_path` 是扫描时写进去的,正常情况下必然满足;但这是一次 rmtree,
    "正常情况下"不足以作为动手的理由。
    """
    package = db.get(PluginPackage, package_id)
    if package is None:
        raise PluginDomainError("pluginErr_notFound")
    from app.domain.plugins import bundled

    # 随应用发的插件卸不掉:下次启动对账又会把它装回来(见 bundled),而「我删了它怎么又回来了」
    # 比「这个删不了」更让人困惑。不想用就停用它的连接。
    if bundled.is_bundled(package_id):
        raise PluginDomainError("pluginErr_bundledCannotUninstall", name=package.name)
    raw = (package.manifest or {}).get(PATH_KEY)
    if raw:
        path = Path(str(raw)).resolve()
        root = plugins_dir.resolve()
        if path.parent == root and path.is_dir() and _has_manifest(path):
            shutil.rmtree(path)
        elif path.is_dir():
            logger.warning("plugin %s: refusing to remove %s (not a direct child of %s)", package_id, path, root)
    # 持久目录随包一起走:卸载后留着它,下次装回来就会读到上一个版本攒下的东西(甚至别人的)。
    shutil.rmtree(data_dir_for(package_id), ignore_errors=True)
    db.delete(package)
    db.commit()


def _prune(db: Session, plugins_dir: Path) -> None:
    """目录已经不在了的包记录一并删掉。

    **判据是每个包自己的目录**,不是"这次扫到了谁"。两者在正常情况下等价,但在异常情况下
    差别很大:插件目录整体读不到时(权限、外挂盘没挂上),按"没扫到"会把**全部**记录连同
    已授的权限和已填的凭据一起抹掉;按各自的目录则只删真的不见了的那些。
    """
    if not plugins_dir.is_dir():
        return
    root = plugins_dir.resolve()
    for package in db.scalars(select(PluginPackage)):
        raw = (package.manifest or {}).get(PATH_KEY)
        if not raw:
            continue
        path = Path(str(raw))
        if root not in path.resolve().parents:
            continue
        if not _has_manifest(path):
            logger.info("plugin %s removed: %s no longer holds a manifest", package.id, path)
            db.delete(package)


def _has_manifest(path: Path) -> bool:
    return any((path / name).exists() for name in MANIFEST_FILENAMES)


def _iter_manifest_paths(plugins_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for child in sorted(plugins_dir.iterdir()):
        # 隐藏目录是安装 / 对账的暂存与替换现场(`.<id>.installing-…`、`.<id>.replaced-…`,见
        # registry.install_archive 与 bundled.install):里面有一份完整的清单,扫到它就会把包记录的
        # 目录指到一个马上要被删掉的地方。
        if not child.is_dir() or child.name.startswith("."):
            continue
        for filename in MANIFEST_FILENAMES:
            if (child / filename).exists():
                paths.append(child / filename)
                break
    return paths


def _load(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PluginDomainError("pluginErr_manifestNotJson", path=str(path)) from exc
    if not isinstance(raw, dict):
        raise PluginDomainError("pluginErr_manifestNotObject", path=str(path))
    return raw


def instances_of(db: Session, package_id: str) -> list[PluginInstance]:
    return list(
        db.scalars(
            select(PluginInstance).where(PluginInstance.package_id == package_id).order_by(PluginInstance.created_at)
        )
    )


__all__ = ["MANIFEST_FILENAMES", "instances_of", "register", "scan", "uninstall"]
