"""扫描 + 把实例那一侧对齐。**编排层** —— 它认识 packages 和 instances,那两个互不认识。

拆开是为了不成环:`packages` 只管磁盘↔记录,`instances` 只管一次接入。"扫完之后要给新包建
默认连接、把改过分类的字段搬位置、给新工具补开关"是三件跨两边的事,归这里。
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import PluginInstance, PluginPackage
from app.domain.plugins import instances as inst
from app.domain.plugins import packages as pkg
from app.domain.plugins.manifest import Manifest, manifest_of


def sync(db: Session, plugins_dir: Path, *, owner_user_id: str = "") -> list[PluginPackage]:
    """扫描插件目录并把实例对齐。插件页的「扫描插件」走这条。"""
    scanned = pkg.scan(db, plugins_dir)
    for package in scanned:
        manifest = manifest_of(package)
        _ensure_default_instance(db, package, manifest, owner_user_id)
        for instance in pkg.instances_of(db, package.id):
            # 作者把某个字段从凭据改成配置(或反过来)时,把用户早就填过的值搬到新位置 ——
            # 重填是我们的问题,不是他的。
            inst.reconcile_fields(db, instance, manifest)
            _seed(db, instance, manifest)
    return scanned


def _ensure_default_instance(
    db: Session, package: PluginPackage, manifest: Manifest, owner_user_id: str
) -> None:
    """无配置无凭据的包装上就建一个默认连接 —— 那种插件不该逼用户先"新建一个连接"。

    有配置的包不自动建:建之前我们不知道它连的是哪个端点,也就不知道它该叫什么名字,
    而一个叫「TikHub」却没配平台的空壳只会让人以为它坏了。

    **建给扫描的那个人**(接入归人,见 db.models.PluginInstance)。"自动建一个大家共用的"
    在归属拆开之后没有意义 —— 它会是一个没有主人、却记着某个人调用的接入。别人一键就能建
    自己的那一个。
    """
    if manifest.config or manifest.credentials:
        return
    if not owner_user_id:
        return
    if [i for i in pkg.instances_of(db, package.id) if i.owner_user_id == owner_user_id]:
        return
    inst.create(db, package.id, {}, manifest.name, owner_user_id=owner_user_id)


def _seed(db: Session, instance: PluginInstance, manifest: Manifest) -> None:
    """给还没有开关记录的工具建一条。

    扫描是「我们刚知道这个包有哪些工具」的时刻,所以在这里补 —— 否则进程类插件的开关要等到
    下一次启用才出现,而已经启用着的连接根本等不到那一次,界面上就一直停在「已开启 0 / 2」。
    MCP 连接的清单要连上服务才知道,它的补种在 tools.refresh_tools 里。
    """
    if manifest.is_mcp:
        return
    inst.seed_capabilities(db, instance, manifest, [str(t["name"]) for t in manifest.declared_tools if t.get("name")])


__all__ = ["sync"]
