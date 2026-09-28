"""某个人把哪一个插件连接定为某项能力的默认(素材外链、文档解析……,见 domain/capabilities)。

用哪一家由他在「设置 → 能力提供方」里定;挑法读它。只能定**自己的**、**声明了这项能力的**连接。
内置实现不存行:没定默认时有内置实现的能力本来就用内置的(见 capabilities.set_default)。
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
        raise PluginDomainError("pluginErr_connectionNotFound")
    if capability not in inst.manifest_for(db, instance).provides:
        raise PluginDomainError("pluginErr_capabilityNotDeclared", name=instance.name, capability=capability)
    if row is None:
        db.add(PluginCapabilityDefault(owner_user_id=owner_user_id, capability=capability, instance_id=instance.id))
    else:
        row.instance_id = instance.id
    db.commit()
