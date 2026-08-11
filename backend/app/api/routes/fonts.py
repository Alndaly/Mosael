from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import FontOut
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import Font
from app.domain.fonts import FontError, delete_font_files, import_uploaded_font
from app.media.paths import resolve_key

router = APIRouter(tags=["fonts"])

_MEDIA_TYPES = {
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".ttc": "font/collection",
    ".otc": "font/collection",
}


def _require_font(db: DbSession, user: CurrentUser, font_id: str, *, perm: str | None = None) -> Font:
    font = db.get(Font, font_id)
    if font is None:
        raise HTTPException(status_code=404, detail="Font not found")
    if perm is None:
        ensure_workspace_access(db, user, font.workspace_id)
    else:
        ensure_workspace_perm(db, user, font.workspace_id, perm)
    return font


@router.get("/fonts", response_model=list[FontOut])
def list_fonts(workspace_id: str, db: DbSession, user: CurrentUser) -> list[Font]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(Font).where(Font.workspace_id == workspace_id).order_by(Font.created_at.desc())
    return list(db.scalars(stmt))


@router.post("/fonts", response_model=FontOut)
def upload_font(
    db: DbSession,
    user: CurrentUser,
    workspace_id: str = Form(...),
    file: UploadFile = File(...),
) -> Font:
    ensure_workspace_perm(db, user, workspace_id, "upload")
    try:
        return import_uploaded_font(db, workspace_id=workspace_id, upload=file)
    except FontError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/fonts/{font_id}/file")
def get_font_file(font_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    """Serves the font to the preview's @font-face. Auth still applies — like the other media
    routes this is reached with the token as a query param, since a CSS url() sends no headers."""
    font = _require_font(db, user, font_id)
    path = resolve_key(font.file_key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Font file is missing")
    suffix = path.suffix.lower()
    return FileResponse(path, media_type=_MEDIA_TYPES.get(suffix, "application/octet-stream"))


@router.delete("/fonts/{font_id}", status_code=204)
def delete_font(font_id: str, db: DbSession, user: CurrentUser) -> Response:
    font = _require_font(db, user, font_id, perm="upload")
    delete_font_files(font)
    db.delete(font)
    db.commit()
    return Response(status_code=204)
