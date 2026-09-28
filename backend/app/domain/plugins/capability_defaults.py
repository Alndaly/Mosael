"""某个人把哪一家定为某项能力的默认(素材外链、文档解析、降噪……,见 domain/capabilities)。

用哪一家由他在「设置 → 能力提供方」里定;挑法读它。那一家是**自己的**、**声明了这项能力的**连接,或这项能力的
某个内置实现(调用方给出这项能力有哪几个内置实现 —— 这里不认识降噪引擎)。选「不定时本来就会用的那个」内置实现
不存行(见 capabilities.set_default)。
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import PluginCapabilityDefault, PluginInstance
from app.domain.plugins import instances as inst
from app.domain.plugins.errors import PluginDomainError


def default_of(db: Session, owner_user_id: str, capability: str) -> str | None:
    row = db.get(PluginCapabilityDefault, (owner_user_id, capability))
    return (row.instance_id or row.builtin_id) if row else None


def set_default(db: Session, owner_user_id: str, capability: str, provider_id: str | None,
                *, builtin_ids: frozenset[str] = frozenset()) -> None:
    """定下(或清掉,`provider_id=None`)这个人在这项能力上的默认。`builtin_ids`:这项能力的内置实现有哪几个。"""
    row = db.get(PluginCapabilityDefault, (owner_user_id, capability))
    if provider_id is None:
        if row is not None:
            db.delete(row)
            db.commit()
        return
    if provider_id in builtin_ids:
        instance_id, builtin_id = None, provider_id
    else:
        instance = db.get(PluginInstance, provider_id)
        if instance is None or instance.owner_user_id != owner_user_id:
            raise PluginDomainError("pluginErr_connectionNotFound")
        if capability not in inst.manifest_for(db, instance).provides:
            raise PluginDomainError("pluginErr_capabilityNotDeclared", name=instance.name, capability=capability)
        instance_id, builtin_id = instance.id, None
    if row is None:
        db.add(PluginCapabilityDefault(owner_user_id=owner_user_id, capability=capability,
                                       instance_id=instance_id, builtin_id=builtin_id))
    else:
        row.instance_id, row.builtin_id = instance_id, builtin_id
    db.commit()
