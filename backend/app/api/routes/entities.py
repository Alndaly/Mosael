"""资产库(ADR 0027)的接口:人物 / 场景 / 道具、参考图、变体、封面,以及反查。

领域在 domain/entities;闸在 domain/entities/use_cases(每个资产先查它在哪个工作区,再按那个工作区过闸)。
这里只认人、把行翻成出口的形状(entity_out / summaries_out,智能体工具也用它们)。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import select

from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas import (
    AssetEntityOut,
    EntityCatalogOut,
    EntityCreate,
    EntityDrawRequest,
    EntityOut,
    EntityReferenceAdd,
    EntityReferenceOrder,
    EntityReferenceUpdate,
    EntitySummaryOut,
    EntityUpdate,
    EntityUsageOut,
    EntityVariantCreate,
    JobOut,
)
from app.core.i18n import get_current_locale, t
from app.db.models import Entity, Job
from app.domain import entities as library
from app.domain.entities.catalog import ATTACH_PRIORITY, ATTRIBUTE_KEYS, CONSENT_KINDS, KINDS, ROLES, ROLES_BY_KIND
from app.domain.entities import use_cases

router = APIRouter(tags=["entities"])


def summaries_out(db: Session, rows: list[Entity]) -> list[EntitySummaryOut]:
    refs, variants, first = library.counts_for(db, [row.id for row in rows])
    parents = {
        parent.id: parent.name
        for parent in db.scalars(select(Entity).where(Entity.id.in_({row.parent_id for row in rows if row.parent_id})))
    }
    return [
        EntitySummaryOut(
            id=row.id,
            kind=row.kind,
            parent_id=row.parent_id,
            parent_name=parents.get(row.parent_id or "", ""),
            name=row.name,
            cover_asset_id=library.cover_of(row, first.get(row.id)),
            tags=list(row.tags or []),
            reference_count=refs.get(row.id, 0),
            variant_count=variants.get(row.id, 0),
            updated_at=row.updated_at,
        )
        for row in rows
    ]


def entity_out(db: Session, entity: Entity) -> EntityOut:
    references = library.references_of(db, entity.id)
    first_image = next((asset.id for _, asset in references if asset.kind == "image"), None)
    parent = db.get(Entity, entity.parent_id) if entity.parent_id else None
    return EntityOut(
        id=entity.id,
        workspace_id=entity.workspace_id,
        kind=entity.kind,
        parent_id=entity.parent_id,
        parent_name=parent.name if parent is not None else "",
        name=entity.name,
        description=entity.description,
        prompt=entity.prompt,
        cover_asset_id=entity.cover_asset_id,
        display_cover_asset_id=library.cover_of(entity, first_image),
        attributes=dict(entity.attributes or {}),
        tags=list(entity.tags or []),
        lost_references=list(entity.lost_references or []),
        references=[
            {
                "asset_id": ref.asset_id,
                "role": ref.role,
                "position": ref.position,
                "asset_kind": asset.kind,
                "asset_name": asset.name,
            }
            for ref, asset in references
        ],
        variants=summaries_out(db, library.variants_of(db, entity.id)),
        usable_for_digital_human=library.usable_for_digital_human(dict(entity.attributes or {})),
        created_at=entity.created_at,
        updated_at=entity.updated_at,
    )


@router.get("/entities/catalog", response_model=EntityCatalogOut)
def entity_catalog(db: DbSession, user: CurrentUser) -> dict[str, Any]:
    """资产的词表,按请求方的语言翻好。界面上角度的名字、授权选项的说明都读这一份。"""
    locale = get_current_locale()
    return {
        "kinds": [{"kind": kind, "label": t(f"entityKind_{kind}", locale)} for kind in KINDS],
        "roles": [{"role": role, "label": t(f"entityRole_{role}", locale)} for role in ROLES],
        "consent_kinds": [
            {"kind": kind, "label": t(f"entityConsent_{kind}", locale), "help": t(f"entityConsent_{kind}_help", locale)}
            for kind in CONSENT_KINDS
        ],
        "roles_by_kind": {kind: list(roles) for kind, roles in ROLES_BY_KIND.items()},
        "attach_priority": {kind: list(order) for kind, order in ATTACH_PRIORITY.items()},
        "attributes": {kind: list(keys) for kind, keys in ATTRIBUTE_KEYS.items()},
    }


@router.get("/entities", response_model=list[EntitySummaryOut])
def list_entities(
    workspace_id: str,
    db: DbSession,
    user: CurrentUser,
    kind: str = "",
    tag: str = "",
    q: str = Query(default="", max_length=200),
    parent_id: str = "",
    include_variants: bool = False,
) -> list[EntitySummaryOut]:
    rows = use_cases.list_entities(
        db, user, workspace_id, kind=kind, tag=tag, query=q, parent_id=parent_id, include_variants=include_variants
    )
    return summaries_out(db, rows)


@router.post("/entities", response_model=EntityOut)
def create_entity(body: EntityCreate, db: Tx, user: CurrentUser) -> EntityOut:
    entity = use_cases.create(
        db,
        user,
        body.workspace_id,
        kind=body.kind,
        name=body.name,
        description=body.description,
        prompt=body.prompt,
        attributes=body.attributes,
        tags=body.tags,
        parent_id=body.parent_id,
    )
    return entity_out(db, entity)


@router.get("/entities/{entity_id}", response_model=EntityOut)
def read_entity(entity_id: str, db: DbSession, user: CurrentUser) -> EntityOut:
    return entity_out(db, use_cases.entity(db, user, entity_id))


@router.patch("/entities/{entity_id}", response_model=EntityOut)
def update_entity(entity_id: str, body: EntityUpdate, db: Tx, user: CurrentUser) -> EntityOut:
    changes = {name: getattr(body, name) for name in body.model_fields_set}
    return entity_out(db, use_cases.update(db, user, entity_id, **changes))


@router.delete("/entities/{entity_id}", status_code=204)
def delete_entity(entity_id: str, db: Tx, user: CurrentUser, with_variants: bool = False) -> Response:
    """删资产**不删素材**。有变体时要 `with_variants=true`(界面在确认框里写清有几个变体)。"""
    use_cases.delete(db, user, entity_id, with_variants=with_variants)
    return Response(status_code=204)


@router.post("/entities/{entity_id}/variants", response_model=EntityOut)
def create_variant(entity_id: str, body: EntityVariantCreate, db: Tx, user: CurrentUser) -> EntityOut:
    variant = use_cases.create_variant(
        db,
        user,
        entity_id,
        name=body.name,
        description=body.description,
        prompt=body.prompt,
        attributes=body.attributes,
    )
    return entity_out(db, variant)


@router.delete("/entities/{entity_id}/lost-references", response_model=EntityOut)
def dismiss_lost_references(entity_id: str, db: Tx, user: CurrentUser) -> EntityOut:
    """「少了哪几张参考图」那句提示看过了。"""
    return entity_out(db, use_cases.dismiss_lost_references(db, user, entity_id))


@router.post("/entities/{entity_id}/references", response_model=EntityOut)
def add_reference(entity_id: str, body: EntityReferenceAdd, db: Tx, user: CurrentUser) -> EntityOut:
    return entity_out(db, use_cases.add_reference(db, user, entity_id, body.asset_id, body.role, cover=body.cover))


@router.put("/entities/{entity_id}/references/order", response_model=EntityOut)
def reorder_references(entity_id: str, body: EntityReferenceOrder, db: Tx, user: CurrentUser) -> EntityOut:
    return entity_out(db, use_cases.reorder_references(db, user, entity_id, body.asset_ids))


@router.patch("/entities/{entity_id}/references/{asset_id}", response_model=EntityOut)
def update_reference(
    entity_id: str, asset_id: str, body: EntityReferenceUpdate, db: Tx, user: CurrentUser
) -> EntityOut:
    return entity_out(db, use_cases.set_reference_role(db, user, entity_id, asset_id, body.role))


@router.delete("/entities/{entity_id}/references/{asset_id}", response_model=EntityOut)
def remove_reference(entity_id: str, asset_id: str, db: Tx, user: CurrentUser) -> EntityOut:
    """摘掉一张参考图。素材还在素材库里。"""
    return entity_out(db, use_cases.remove_reference(db, user, entity_id, asset_id))


@router.post("/entities/{entity_id}/draw", response_model=JobOut)
def draw_entity(entity_id: str, body: EntityDrawRequest, db: Tx, user: CurrentUser) -> Job:
    """照这个资产的参考图再画几张(补全多角度 / 生成表情),画成的挂回来。付费生成,闸和生成页同一道(`ai`)。

    说不通的(没图、模型不收参考图、角度都齐了)当场 422,不起任务;说得通就回那个任务,界面跟着它的进度。
    """
    from app.core.i18n import render_message
    from app.domain.workflows import WorkflowDomainError

    config = {"model": body.model, "scope": body.scope, "expressions": body.expressions, "text": body.text}
    try:
        return use_cases.draw(db, user, entity_id, body.ability, config)
    except WorkflowDomainError as exc:
        detail = render_message(exc.key, get_current_locale(), exc.params) if exc.key else str(exc)
        raise HTTPException(status_code=422, detail=detail) from exc


@router.get("/entities/{entity_id}/usage", response_model=EntityUsageOut)
def entity_usage(entity_id: str, db: DbSession, user: CurrentUser) -> dict[str, Any]:
    """在哪里用过:画板(资产格 / 提示词里 @ 了它)、生成记录(请求里点名了它)、工作流(生成节点点名了它)。"""
    _entity, usage = use_cases.usage(db, user, entity_id)
    return {
        "boards": [{"id": board.id, "name": board.name, "how": how} for board, how in usage.boards],
        "generations": [
            {
                "id": one.id,
                "session_id": one.session_id,
                "kind": one.kind,
                "provider_profile_id": one.provider_profile_id,
                "model": one.model,
                "prompt": str((one.request or {}).get("prompt") or "")[:200],
                "result_asset_id": one.result_asset_id,
                "created_at": one.created_at,
            }
            for one in usage.generations
        ],
        "workflows": [{"id": flow.id, "name": flow.name} for flow in usage.workflows],
    }


@router.get("/assets/{asset_id}/entities", response_model=list[AssetEntityOut])
def asset_entities(asset_id: str, db: DbSession, user: CurrentUser) -> list[dict[str, Any]]:
    """这份素材是哪些资产的参考图(素材详情里的「属于哪些资产」)。"""
    return [
        {
            "id": row.entity.id,
            "kind": row.entity.kind,
            "name": row.entity.name,
            "parent_id": row.entity.parent_id,
            "parent_name": row.parent.name if row.parent is not None else "",
            "role": row.role,
        }
        for row in use_cases.of_asset(db, user, asset_id)
    ]
