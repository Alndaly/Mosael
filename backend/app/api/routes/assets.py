from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.schemas import AssetCreate, AssetOut
from app.db.models import Asset
from app.domain.assets import import_uploaded_asset

router = APIRouter(tags=["assets"])


@router.post("/assets", response_model=AssetOut)
def create_asset(body: AssetCreate, db: DbSession) -> Asset:
    asset = Asset(**body.model_dump())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/assets/import", response_model=AssetOut)
def import_asset(
    db: DbSession,
    workspace_id: str = Form(...),
    project_id: str | None = Form(None),
    name: str | None = Form(None),
    file: UploadFile = File(...),
) -> Asset:
    return import_uploaded_asset(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        name=name,
        upload=file,
    )


@router.get("/assets", response_model=list[AssetOut])
def list_assets(workspace_id: str, db: DbSession, project_id: str | None = None) -> list[Asset]:
    stmt = select(Asset).where(Asset.workspace_id == workspace_id)
    if project_id:
        stmt = stmt.where(Asset.project_id == project_id)
    stmt = stmt.order_by(Asset.created_at.desc())
    return list(db.scalars(stmt))
