"""把**随应用一起发**的插件装进插件目录并登记(哪几个、在哪儿见 bundled)。

**每次启动对账**(`install-bundled-plugins`,recurring 迁移步骤):插件目录里没有、或内容和这一版带的
不一样,就整目录换成这一版的,再登记包记录。判据是**内容指纹**不是版本号 —— 开发时改了插件代码
没改版本号,也该在下次启动时生效;发版时两者本来就一起变。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import PluginPackage
from app.domain.plugins import instances, packages
from app.domain.plugins.bundled import DIGEST_FILENAME, plugins
from app.domain.plugins.manifest import manifest_of
from app.domain.plugins.migrations import CANONICAL_FILENAME

logger = logging.getLogger(__name__)


def install(db: Session, plugins_dir: Path) -> list[str]:
    """把这一版带的插件装进插件目录并登记。返回这次真的换了内容的那几个 id。"""
    plugins_dir.mkdir(parents=True, exist_ok=True)
    replaced: list[str] = []
    for plugin in plugins():
        target = plugins_dir / plugin.id
        marker = target / DIGEST_FILENAME
        current = marker.read_text(encoding="utf-8").strip() if marker.is_file() else ""
        digest = plugin.digest
        if current != digest:
            # 先拷到旁边再换过去:拷到一半断电,留下的是一个没用的临时目录,不是半个插件。
            staging = plugins_dir / f".{plugin.id}.installing"
            shutil.rmtree(staging, ignore_errors=True)
            shutil.copytree(plugin.source, staging, ignore=shutil.ignore_patterns("__pycache__"))
            (staging / DIGEST_FILENAME).write_text(digest, encoding="utf-8")
            if target.exists():
                shutil.rmtree(target)
            staging.rename(target)
            replaced.append(plugin.id)
            logger.info("装上随应用发的插件 %s", plugin.id)
        package = packages.register(db, target / CANONICAL_FILENAME)
        db.flush()
        _seed_new_tools(db, package)
    db.commit()
    return replaced


def _seed_new_tools(db: Session, package: PluginPackage) -> None:
    """新版本多了工具:给**已经接好**的连接补上开关(按清单的 recommended / expose 预勾)。

    不补的话,升级之后插件页上新工具一个都没开,智能体和工作流里也看不到 —— 而用户什么都没做错,
    只是那几个工具在他建连接的时候还不存在。已有的开关不动(那是用户的选择)。
    """
    manifest = manifest_of(package)
    names = [str(tool["name"]) for tool in manifest.declared_tools if tool.get("name")]
    for instance in packages.instances_of(db, package.id):
        instances.seed_capabilities(db, instance, manifest, names)


__all__ = ["install"]
