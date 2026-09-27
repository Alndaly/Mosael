"""资产库节点(ADR 0027 阶段 4):「取资产」把一个人物 / 场景 / 道具交给下游,「存成资产」把一套画好的图存回资产库。

两个节点合起来就是「先认已有的、新的存下来」:按名字取不到(`found = 0`)再去画,画完存成资产 ——
下一部片子里的同一个角色,是同一张脸。规矩都在 domain/entities:取出来的提示词描述和参考图先后和 `@资产`
同一份(`generation_profile`),存的时候校验和界面同一份(`create_entity` / `add_reference`)。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.jobs import current_actor
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import RunScope, register
from app.domain.workflows.executors.common import id_list

#: 取资产时最多交出几张参考图(按挑图的先后)。
DEFAULT_REFERENCE_LIMIT = 8
#: 「存成资产」遇到同种类同名的资产怎么办:合并进去(补参考图、补空着的描述),还是另建一个。
IF_EXISTS = ("merge", "new")


def _text(value: Any) -> str:
    return str(value or "").strip()


@register("entity_get")
def entity_get(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """点名一个资产,或按「种类 + 名字」找一个。点名的找不到是错;按名字找不到不是错,`found` 给 0 ——
    那正是「这个角色还没有,先去画」的分支。"""
    from app.domain.entities import EntityDomainError, find_by_name, generation_profile, get_entity

    entity_id = _text(config.get("entity_id"))
    name = _text(config.get("name"))
    kind = _text(config.get("kind"))
    try:
        if entity_id:
            entity = get_entity(db, scope.workspace_id, entity_id)
        elif name and kind:
            entity = find_by_name(db, scope.workspace_id, kind, name)
        else:
            raise WorkflowDomainError("wfErr_entityGetNeedsTarget")
    except EntityDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    if entity is None:
        return {
            "entity_id": "", "found": 0, "name": name, "description": "", "prompt": "",
            "asset_ids": [], "asset_id": "", "voice_engine": "", "voice_id": "",
        }
    display, descriptor, images = generation_profile(db, entity)
    try:
        limit = int(config.get("limit") or DEFAULT_REFERENCE_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_REFERENCE_LIMIT
    picked = images[: max(1, limit)]
    attributes = entity.attributes or {}
    return {
        "entity_id": entity.id,
        "found": 1,
        "name": display,
        "description": entity.description,
        "prompt": descriptor,
        "asset_ids": picked,
        #: 封面:设过的那张,没设就是挑图顺序里的第一张。
        "asset_id": entity.cover_asset_id or (picked[0] if picked else ""),
        "voice_engine": str(attributes.get("voice_engine") or ""),
        "voice_id": str(attributes.get("voice_id") or ""),
    }


@register("entity_save")
def entity_save(db: Session, scope: RunScope, config: dict[str, Any]) -> dict[str, Any]:
    """把一套图存成资产。同种类同名的已经有了,缺省**合并**:补上它还没挂的参考图,提示词描述 / 描述只在
    原来空着时填 —— 人手改过的不被一次运行覆盖。选「另建一个」就总是新建。"""
    from app.domain.entities import (
        EntityDomainError,
        add_reference,
        create_entity,
        find_by_name,
        references_of,
        update_entity,
    )

    kind = _text(config.get("kind"))
    name = _text(config.get("name"))
    if not name:
        raise WorkflowDomainError("wfErr_entitySaveNeedsName")
    mode = _text(config.get("if_exists")) or "merge"
    if mode not in IF_EXISTS:
        raise WorkflowDomainError("wfErr_entitySaveIfExists", params={"options": " / ".join(IF_EXISTS)})
    description = _text(config.get("description"))
    prompt = _text(config.get("prompt"))
    role = _text(config.get("role"))
    asset_ids = list(dict.fromkeys(id_list(config.get("asset_ids"))))
    actor = current_actor(db)
    try:
        existing = find_by_name(db, scope.workspace_id, kind, name) if mode == "merge" else None
        if existing is None:
            entity = create_entity(
                db,
                workspace_id=scope.workspace_id,
                kind=kind,
                name=name,
                description=description,
                prompt=prompt,
                tags=id_list(config.get("tags")),
                actor_id=actor,
            )
            created = True
        else:
            entity = existing
            fill: dict[str, Any] = {}
            if prompt and not entity.prompt.strip():
                fill["prompt"] = prompt
            if description and not entity.description.strip():
                fill["description"] = description
            tags = id_list(config.get("tags"))
            if tags and not set(tags) <= set(entity.tags or []):
                fill["tags"] = [*(entity.tags or []), *(tag for tag in tags if tag not in (entity.tags or []))]
            if fill:
                entity = update_entity(db, entity, actor_id=actor, **fill)
            created = False
        attached = {ref.asset_id for ref, _ in references_of(db, entity.id)}
        added = 0
        for asset_id in asset_ids:
            if asset_id in attached:
                continue
            entity = add_reference(db, entity, asset_id, role)
            attached.add(asset_id)
            added += 1
    except EntityDomainError as exc:
        raise WorkflowDomainError.from_error(exc) from exc
    return {"entity_id": entity.id, "created": 1 if created else 0, "added": added, "name": entity.name}
