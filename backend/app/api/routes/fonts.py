from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas import FontOut
from app.db.models import Font
from app.domain.fonts import FontError
from app.domain.fonts import use_cases as fonts
from app.media.paths import resolve_key

router = APIRouter(tags=["fonts"])

_MEDIA_TYPES = {
    ".ttf": "font/ttf",
    ".otf": "font/otf",
    ".ttc": "font/collection",
    ".otc": "font/collection",
}


@router.get("/fonts", response_model=list[FontOut])
def list_fonts(workspace_id: str, db: DbSession, user: CurrentUser) -> list[Font]:
    return fonts.list_fonts(db, user, workspace_id)


@router.post("/fonts", response_model=FontOut)
def upload_font(
    db: Tx,
    user: CurrentUser,
    workspace_id: str = Form(...),
    file: UploadFile = File(...),
) -> Font:
    try:
        return fonts.upload_font(db, user, workspace_id, file)
    except FontError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/fonts/{font_id}/file")
def get_font_file(font_id: str, db: DbSession, user: CurrentUser) -> FileResponse:
    """Serves the font to the preview's @font-face. Auth still applies — like the other media
    routes this is reached with the token as a query param, since a CSS url() sends no headers."""
    font = fonts.readable_font(db, user, font_id)
    path = resolve_key(font.file_key)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Font file is missing")
    suffix = path.suffix.lower()
    return FileResponse(path, media_type=_MEDIA_TYPES.get(suffix, "application/octet-stream"))


@router.delete("/fonts/{font_id}", status_code=204)
def delete_font(font_id: str, db: Tx, user: CurrentUser) -> Response:
    fonts.delete_font(db, user, font_id)
    return Response(status_code=204)
