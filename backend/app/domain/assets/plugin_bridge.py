"""把素材库接到插件那道缝上。

**这是唯一一处让插件系统和素材库互相认识的地方**,而且方向是单向的:素材这边认识插件的
契约(media_bridge),插件那边什么都不知道。和 agent/receipts 把智能体接到任务总线上是
同一个手法 —— 发布、导出、转写都建任务,它们没有一个该因为「智能体也许想知道」而认识智能体;
同理,插件不该因为「产出也许要进素材库」而认识素材库。

好处不是洁癖:哪天要支持「从一个 URL 取文件交给插件」,在这里登记另一个来源就行,
domain/plugins 一行都不用改。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy.orm import Session

from app.db.models import Asset
from app.domain.plugins import media_bridge
from app.domain.plugins.errors import PluginDomainError
from app.media.paths import resolve_key


def _take(
    db: Session, path: Path, *, workspace_id: str, project_id: str | None, name: str
) -> tuple[str, str]:
    """插件产出 → 素材库。返回 (id, 名字)。"""
    from app.domain.assets import register_file_asset

    asset = register_file_asset(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        source_path=path,
        name=name,
        source="plugin",
    )
    return asset.id, asset.name


def _give(db: Session, ref: str, *, into: Path, workspace_id: str) -> Path:
    """素材库 → 插件。**拷一份**到暂存目录,不给原件。

    给原件的话,插件改坏了或删掉了,用户丢的是库里那一份 —— 而插件是第三方代码。
    拷贝的代价是一次磁盘 IO,换的是"插件怎么折腾都伤不到库"。
    """
    asset = db.get(Asset, ref)
    if asset is None:
        raise PluginDomainError(f"素材不存在: {ref}")
    # **跨工作区不给。** 插件的调用方可能是智能体,而它拿到的 id 可能来自任何地方 ——
    # 这一条挡的是"用 A 工作区的连接把 B 工作区的素材传出去"。
    if asset.workspace_id != workspace_id:
        raise PluginDomainError("这份素材不属于当前工作区")
    if not asset.file_key:
        raise PluginDomainError(f"素材 {asset.name} 还没有文件(可能仍在生成中)")
    origin = resolve_key(asset.file_key)
    if not origin.is_file():
        raise PluginDomainError(f"素材 {asset.name} 的文件已丢失")
    target = into / (asset.original_filename or asset.name or origin.name)
    shutil.copy2(origin, target)
    return target


def install() -> None:
    media_bridge.use_sink(_take)
    media_bridge.use_source(_give)


__all__ = ["install"]
