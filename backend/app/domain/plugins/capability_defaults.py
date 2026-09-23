"""某个人把哪一个插件连接定为某项能力的默认(今天只有 `public_url`:素材外链)。

一个人配了几家对象存储时,用哪一家由他在设置里定(「设置 → 素材外链」);生成时
读它(见 generation/public_links)。只能定**自己的**、**声明了这项能力的**连接。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import PluginCapabilityDefault, PluginInstance
from app.domain.plugins import instances as inst
from app.domain.plugins.errors import PluginDomainError


def default_of(db: Session, owner_user_id: str, capability: str) -> str | None:
    row = db.get(PluginCapabilityDefault, (owner_user_id, capability))
    return row.instance_id if row else None


def set_default(db: Session, owner_user_id: str, capability: str, instance_id: str | None) -> None:
    """定下(或清掉,`instance_id=None`)这个人在这项能力上的默认连接。"""
    row = db.get(PluginCapabilityDefault, (owner_user_id, capability))
    if instance_id is None:
        if row is not None:
            db.delete(row)
            db.commit()
        return
    instance = db.get(PluginInstance, instance_id)
    if instance is None or instance.owner_user_id != owner_user_id:
        raise PluginDomainError("没有这个连接")
    if capability not in inst.manifest_for(db, instance).provides:
        raise PluginDomainError(f"「{instance.name}」没有声明「{capability}」这项能力")
    if row is None:
        db.add(PluginCapabilityDefault(owner_user_id=owner_user_id, capability=capability, instance_id=instance.id))
    else:
        row.instance_id = instance.id
    db.commit()
