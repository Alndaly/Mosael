"""资产库条目「出口的样子」:列表里的一行(`summaries`)与详情(`detail`)。

资产库接口和智能体的 list_entities / get_entity / create_entity …… 读的是同一份。此前这两段组装长在
路由里(`entity_out / summaries_out`),智能体工具只能反过来 import 路由模块;收进领域后两边都调这里,
出参 schema(EntitySummaryOut / EntityOut)由入口自己套。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Entity
from app.domain.entities import catalog, library


def summaries(db: Session, rows: list[Entity]) -> list[dict[str, Any]]:
    """列表的行:引用数、变体数、封面(没设封面取第一张图)一次查齐。"""
    refs, variants, first = library.counts_for(db, [row.id for row in rows])
    parents = library.parent_names(db, rows)
    return [
        {
            "id": row.id,
            "kind": row.kind,
            "parent_id": row.parent_id,
            "parent_name": parents.get(row.parent_id or "", ""),
            "name": row.name,
            "cover_asset_id": library.cover_of(row, first.get(row.id)),
            "tags": list(row.tags or []),
            "reference_count": refs.get(row.id, 0),
            "variant_count": variants.get(row.id, 0),
            "updated_at": row.updated_at,
        }
        for row in rows
    ]


def detail(db: Session, entity: Entity) -> dict[str, Any]:
    """一个条目的全部:参考图(带角度)、变体、按种类的属性、能不能做数字人。"""
    references = library.references_of(db, entity.id)
    first_image = next((asset.id for _, asset in references if asset.kind == "image"), None)
    attributes = dict(entity.attributes or {})
    return {
        "id": entity.id,
        "workspace_id": entity.workspace_id,
        "kind": entity.kind,
        "parent_id": entity.parent_id,
        "parent_name": library.parent_names(db, [entity]).get(entity.parent_id or "", ""),
        "name": entity.name,
        "description": entity.description,
        "prompt": entity.prompt,
        "cover_asset_id": entity.cover_asset_id,
        "display_cover_asset_id": library.cover_of(entity, first_image),
        "attributes": attributes,
        "tags": list(entity.tags or []),
        "lost_references": list(entity.lost_references or []),
        "references": [
            {
                "asset_id": ref.asset_id,
                "role": ref.role,
                "position": ref.position,
                "asset_kind": asset.kind,
                "asset_name": asset.name,
            }
            for ref, asset in references
        ],
        "variants": summaries(db, library.variants_of(db, entity.id)),
        "usable_for_digital_human": catalog.usable_for_digital_human(attributes),
        "created_at": entity.created_at,
        "updated_at": entity.updated_at,
    }
