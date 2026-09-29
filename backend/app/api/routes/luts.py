from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas import LutOut, LutUpdate
from app.db.models import Lut
from app.domain.luts import LutError
from app.domain.luts import use_cases as luts

router = APIRouter(tags=["luts"])


@router.get("/luts", response_model=list[LutOut])
def list_luts(workspace_id: str, db: DbSession, user: CurrentUser) -> list[Lut]:
    return luts.list_luts(db, user, workspace_id)


@router.post("/luts", response_model=LutOut)
def upload_lut(
    db: Tx,
    user: CurrentUser,
    workspace_id: str = Form(...),
    name: str | None = Form(None),
    file: UploadFile = File(...),
) -> Lut:
    try:
        return luts.upload_lut(db, user, workspace_id, file, name)
    except LutError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/luts/{lut_id}", response_model=LutOut)
def rename_lut(lut_id: str, body: LutUpdate, db: Tx, user: CurrentUser) -> Lut:
    return luts.rename_lut(db, user, lut_id, body.name)


@router.delete("/luts/{lut_id}", status_code=204)
def delete_lut(lut_id: str, db: Tx, user: CurrentUser) -> Response:
    luts.delete_lut(db, user, lut_id)
    return Response(status_code=204)
