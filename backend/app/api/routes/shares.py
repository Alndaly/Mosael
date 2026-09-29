from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.deps import CurrentUser, DbSession, Tx
from app.domain import sharing
from app.domain.sharing import use_cases as shares

router = APIRouter(tags=["shares"])

"""把「我的东西」放进一个工作区,或者收回来。只认主人(见 domain/sharing/use_cases)。"""


class ShareRequest(BaseModel):
    workspace_id: str


@router.post("/shares/{kind}/{resource_id}")
def share_resource(kind: str, resource_id: str, body: ShareRequest, db: Tx, user: CurrentUser) -> dict:
    try:
        workspaces = shares.share(db, user, kind, resource_id, body.workspace_id)
    except sharing.SharingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"kind": kind, "resource_id": resource_id, "workspaces": workspaces}


@router.delete("/shares/{kind}/{resource_id}")
def unshare_resource(kind: str, resource_id: str, body: ShareRequest, db: Tx, user: CurrentUser) -> dict:
    try:
        workspaces = shares.unshare(db, user, kind, resource_id, body.workspace_id)
    except sharing.SharingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"kind": kind, "resource_id": resource_id, "workspaces": workspaces}


@router.get("/shares/{kind}/{resource_id}")
def list_shares(kind: str, resource_id: str, db: DbSession, user: CurrentUser) -> dict:
    try:
        return shares.shares_of(db, user, kind, resource_id)
    except sharing.SharingError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
