from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    DeliveryKindOut,
    DeliveryStartRequest,
    DeliveryTargetCreate,
    DeliveryTargetOut,
    DeliveryTargetUpdate,
    DeliveryTaskOut,
)
from app.core.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import Asset, DeliveryTarget, DeliveryTask
from app.domain.delivery import (
    DELIVERY_KINDS,
    DeliveryDomainError,
    create_target,
    list_targets,
    start_delivery,
    task_with_status,
)

router = APIRouter(tags=["delivery"])


@router.get("/delivery/kinds", response_model=list[DeliveryKindOut])
def list_kinds(user: CurrentUser) -> list[DeliveryKindOut]:
    return [
        DeliveryKindOut(kind=kind, label=meta["label"], description=meta["description"], config=meta["config"])
        for kind, meta in DELIVERY_KINDS.items()
    ]


@router.get("/delivery/targets", response_model=list[DeliveryTargetOut])
def list_delivery_targets(workspace_id: str, db: DbSession, user: CurrentUser) -> list[DeliveryTarget]:
    ensure_workspace_access(db, user, workspace_id)
    return list_targets(db, workspace_id)


@router.post("/delivery/targets", response_model=DeliveryTargetOut)
def create_delivery_target(body: DeliveryTargetCreate, db: DbSession, user: CurrentUser) -> DeliveryTarget:
    # 交付也是「把成片送出去」,沿用 publish 权限位:能发布的人就能交付,不另立一个权限。
    ensure_workspace_perm(db, user, body.workspace_id, "publish")
    try:
        return create_target(db, workspace_id=body.workspace_id, kind=body.kind, name=body.name, config=body.config)
    except DeliveryDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _require_target(db: DbSession, user: CurrentUser, target_id: str, perm: str) -> DeliveryTarget:
    target = db.get(DeliveryTarget, target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="交付目标不存在")
    ensure_workspace_perm(db, user, target.workspace_id, perm)
    return target


@router.patch("/delivery/targets/{target_id}", response_model=DeliveryTargetOut)
def update_delivery_target(
    target_id: str, body: DeliveryTargetUpdate, db: DbSession, user: CurrentUser
) -> DeliveryTarget:
    target = _require_target(db, user, target_id, "publish")
    if body.name is not None:
        target.name = body.name.strip()[:160] or target.name
    if body.config is not None:
        target.config = body.config
    if body.enabled is not None:
        target.enabled = body.enabled
    db.commit()
    db.refresh(target)
    return target


@router.delete("/delivery/targets/{target_id}", status_code=204)
def delete_delivery_target(target_id: str, db: DbSession, user: CurrentUser) -> None:
    target = _require_target(db, user, target_id, "publish")
    db.delete(target)
    db.commit()


@router.post("/delivery/start", response_model=DeliveryTaskOut)
def start(body: DeliveryStartRequest, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_perm(db, user, body.workspace_id, "publish")
    target = db.get(DeliveryTarget, body.target_id)
    if target is None or target.workspace_id != body.workspace_id:
        raise HTTPException(status_code=404, detail="交付目标不存在")
    asset = db.get(Asset, body.asset_id)
    if asset is None or asset.workspace_id != body.workspace_id:
        raise HTTPException(status_code=404, detail="素材不存在")
    try:
        task = start_delivery(
            db,
            workspace_id=body.workspace_id,
            target=target,
            asset=asset,
            title=body.title,
            description=body.description,
            tags=body.tags,
        )
    except DeliveryDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return task_with_status(db, task)


@router.get("/delivery/tasks", response_model=list[DeliveryTaskOut])
def list_delivery_tasks(workspace_id: str, db: DbSession, user: CurrentUser, limit: int = 100) -> list[dict]:
    ensure_workspace_access(db, user, workspace_id)
    tasks = db.scalars(
        select(DeliveryTask)
        .where(DeliveryTask.workspace_id == workspace_id)
        .order_by(DeliveryTask.created_at.desc())
        .limit(max(1, min(limit, 500)))
    ).all()
    return [task_with_status(db, task) for task in tasks]
