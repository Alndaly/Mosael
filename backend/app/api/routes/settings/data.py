from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, File, HTTPException, UploadFile
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from app.api.deps import CurrentUser, DbSession
from app.domain.data_management import RestoreValidationError, create_backup_archive, stage_restore_archive
from app.domain.permissions import ensure_deployment_admin

router = APIRouter(prefix="/settings/data", tags=["settings"])


@router.post("/backup", response_class=FileResponse)
def download_backup(db: DbSession, user: CurrentUser) -> FileResponse:
    ensure_deployment_admin(db, user)
    archive = create_backup_archive()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return FileResponse(
        archive,
        media_type="application/zip",
        filename=f"Mosael-{stamp}.mosael-backup",
        background=BackgroundTask(archive.unlink, missing_ok=True),
    )


@router.post("/restore/stage")
def stage_restore(
    db: DbSession,
    user: CurrentUser,
    file: UploadFile = File(...),
) -> dict:
    ensure_deployment_admin(db, user)
    try:
        stage_id, manifest = stage_restore_archive(file.file)
    except RestoreValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "stage_id": stage_id,
        "source_app_version": manifest.get("app_version"),
        "created_at": manifest.get("created_at"),
    }
