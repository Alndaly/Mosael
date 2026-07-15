from __future__ import annotations

import mimetypes

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import AssetCreate, AssetOut, TranscriptAttachRequest, TranscriptOut
from app.core.permissions import ensure_workspace_access, require_asset
from app.db.models import Asset, Transcript
from app.domain.assets import import_uploaded_asset
from app.domain.transcripts import attach_transcript, get_transcript_for_asset
from app.domain.transcripts.operations import SegmentIn, TokenIn, TranscriptDomainError
from app.media.paths import resolve_key
from app.media.thumbnails import thumbnail_path

router = APIRouter(tags=["assets"])


@router.post("/assets", response_model=AssetOut)
def create_asset(body: AssetCreate, db: DbSession, user: CurrentUser) -> Asset:
    ensure_workspace_access(db, user, body.workspace_id)
    asset = Asset(**body.model_dump())
    db.add(asset)
    db.commit()
    db.refresh(asset)
    return asset


@router.post("/assets/import", response_model=AssetOut)
def import_asset(
    db: DbSession,
    user: CurrentUser,
    workspace_id: str = Form(...),
    project_id: str | None = Form(None),
    name: str | None = Form(None),
    file: UploadFile = File(...),
) -> Asset:
    ensure_workspace_access(db, user, workspace_id)
    return import_uploaded_asset(
        db,
        workspace_id=workspace_id,
        project_id=project_id,
        name=name,
        upload=file,
    )


@router.get("/assets", response_model=list[AssetOut])
def list_assets(workspace_id: str, db: DbSession, user: CurrentUser, project_id: str | None = None) -> list[Asset]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(Asset).where(Asset.workspace_id == workspace_id)
    if project_id:
        stmt = stmt.where(Asset.project_id == project_id)
    stmt = stmt.order_by(Asset.created_at.desc())
    return list(db.scalars(stmt))


@router.put("/assets/{asset_id}/transcript", response_model=TranscriptOut)
def put_transcript(asset_id: str, body: TranscriptAttachRequest, db: DbSession, user: CurrentUser) -> Transcript:
    if db.get(Asset, asset_id) is not None:
        require_asset(db, user, asset_id)
    try:
        transcript = attach_transcript(
            db,
            asset_id=asset_id,
            language=body.language,
            source=body.source,
            segments=[
                SegmentIn(
                    start_time=segment.start_time,
                    end_time=segment.end_time,
                    text=segment.text,
                    speaker=segment.speaker,
                    tokens=tuple(
                        TokenIn(start_time=token.start_time, end_time=token.end_time, text=token.text)
                        for token in segment.tokens
                    ),
                )
                for segment in body.segments
            ],
        )
    except TranscriptDomainError as exc:
        message = str(exc)
        status = 404 if "not found" in message.lower() else 422
        raise HTTPException(status_code=status, detail=message) from exc
    return get_transcript_for_asset(db, asset_id) or transcript


@router.get("/assets/{asset_id}/transcript", response_model=TranscriptOut)
def get_transcript(asset_id: str, db: DbSession, user: CurrentUser) -> Transcript:
    require_asset(db, user, asset_id)
    transcript = get_transcript_for_asset(db, asset_id)
    if transcript is None:
        raise HTTPException(status_code=404, detail="Transcript not found")
    return transcript


@router.get("/assets/{asset_id}/file")
def get_asset_file(asset_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    asset = _require_file_backed_asset(db, asset_id)
    ensure_workspace_access(db, user, asset.workspace_id)
    path = resolve_key(asset.file_key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Asset file missing")
    media_type = mimetypes.guess_type(asset.original_filename or path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=asset.original_filename or path.name)


@router.get("/assets/{asset_id}/thumbnail")
def get_asset_thumbnail(asset_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    asset = _require_file_backed_asset(db, asset_id)
    ensure_workspace_access(db, user, asset.workspace_id)
    thumb = thumbnail_path(resolve_key(asset.file_key).parent)
    if not thumb.is_file():
        raise HTTPException(status_code=404, detail="Thumbnail not available")
    return FileResponse(thumb, media_type="image/jpeg")


def _require_file_backed_asset(db: DbSession, asset_id: str) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None or not asset.file_key:
        raise HTTPException(status_code=404, detail="Asset not found")
    return asset
