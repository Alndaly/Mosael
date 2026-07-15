from __future__ import annotations

import mimetypes

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.schemas import AssetCreate, AssetOut
from app.db.models import Asset
from app.domain.assets import import_uploaded_asset
from app.media.paths import resolve_key
from app.media.thumbnails import thumbnail_path

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


@router.get("/assets/{asset_id}/file")
def get_asset_file(asset_id: str, db: DbSession) -> FileResponse:
    asset = _require_file_backed_asset(db, asset_id)
    path = resolve_key(asset.file_key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Asset file missing")
    media_type = mimetypes.guess_type(asset.original_filename or path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=asset.original_filename or path.name)


@router.get("/assets/{asset_id}/thumbnail")
def get_asset_thumbnail(asset_id: str, db: DbSession) -> FileResponse:
    asset = _require_file_backed_asset(db, asset_id)
    thumb = thumbnail_path(resolve_key(asset.file_key).parent)
    if not thumb.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail not available")
    return FileResponse(thumb, media_type="image/jpeg")


def _require_file_backed_asset(db: DbSession, asset_id: str) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None or not asset.file_key:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset
