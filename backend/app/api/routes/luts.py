from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import LutOut, LutUpdate
from app.core.permissions import ensure_workspace_access
from app.db.models import Lut
from app.domain.luts import LutError, delete_lut_files, import_uploaded_lut

router = APIRouter(tags=["luts"])


def _require_lut(db: DbSession, user: CurrentUser, lut_id: str) -> Lut:
    lut = db.get(Lut, lut_id)
    if lut is None:
        raise HTTPException(status_code=404, detail="LUT not found")
    ensure_workspace_access(db, user, lut.workspace_id)
    return lut


@router.get("/luts", response_model=list[LutOut])
def list_luts(workspace_id: str, db: DbSession, user: CurrentUser) -> list[Lut]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(Lut).where(Lut.workspace_id == workspace_id).order_by(Lut.created_at.desc())
    return list(db.scalars(stmt))


@router.post("/luts", response_model=LutOut)
def upload_lut(
    db: DbSession,
    user: CurrentUser,
    workspace_id: str = Form(...),
    name: str | None = Form(None),
    file: UploadFile = File(...),
) -> Lut:
    ensure_workspace_access(db, user, workspace_id)
    try:
        return import_uploaded_lut(db, workspace_id=workspace_id, upload=file, name=name)
    except LutError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/luts/{lut_id}", response_model=LutOut)
def rename_lut(lut_id: str, body: LutUpdate, db: DbSession, user: CurrentUser) -> Lut:
    lut = _require_lut(db, user, lut_id)
    lut.name = body.name.strip() or lut.name
    db.commit()
    db.refresh(lut)
    return lut


@router.delete("/luts/{lut_id}", status_code=204)
def delete_lut(lut_id: str, db: DbSession, user: CurrentUser) -> Response:
    lut = _require_lut(db, user, lut_id)
    delete_lut_files(lut)
    db.delete(lut)
    db.commit()
    return Response(status_code=204)
