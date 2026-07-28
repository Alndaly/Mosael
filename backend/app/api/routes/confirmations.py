from __future__ import annotations

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, ensure_graph_node_privileges
from app.api.schemas import ConfirmationCreate, ConfirmationOut
from app.core.permissions import ensure_workspace_access
from app.db.models import ToolConfirmation
from app.domain.agent.confirmations import (
    ConfirmationError,
    approve_confirmation,
    reject_confirmation,
    request_confirmation,
)

router = APIRouter(tags=["confirmations"])


@router.post("/confirmations", response_model=ConfirmationOut)
def create_confirmation(body: ConfirmationCreate, db: DbSession, user: CurrentUser) -> ToolConfirmation:
    ensure_workspace_access(db, user, body.workspace_id)
    try:
        return request_confirmation(
            db,
            workspace_id=body.workspace_id,
            tool=body.tool,
            payload=body.payload,
            requested_by=body.requested_by,
        )
    except ConfirmationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/confirmations", response_model=list[ConfirmationOut])
def list_confirmations(
    workspace_id: str, db: DbSession, user: CurrentUser, status: str | None = None, limit: int = 30
) -> list[ToolConfirmation]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(ToolConfirmation).where(ToolConfirmation.workspace_id == workspace_id)
    if status:
        stmt = stmt.where(ToolConfirmation.status == status)
    stmt = stmt.order_by(ToolConfirmation.created_at.desc()).limit(min(limit, 100))
    return list(db.scalars(stmt))


@router.get("/confirmations/{confirmation_id}", response_model=ConfirmationOut)
def get_confirmation(confirmation_id: str, db: DbSession, user: CurrentUser) -> ToolConfirmation:
    confirmation = _require(db, user, confirmation_id)
    return confirmation


@router.post("/confirmations/{confirmation_id}/approve", response_model=ConfirmationOut)
def approve(confirmation_id: str, db: DbSession, user: CurrentUser) -> ToolConfirmation:
    confirmation = _require(db, user, confirmation_id)
    # create_workflow / update_workflow 卡片携带整份 graph,批准即落库——这是绕开
    # /api/workflows 路由的第四条落库路径,同样要挡 code 节点。按**审批者**校验:
    # 卡片是他批的,这次执行记在他头上。
    ensure_graph_node_privileges(db, user, (confirmation.payload or {}).get("graph"))
    try:
        return approve_confirmation(db, confirmation)
    except ConfirmationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/confirmations/{confirmation_id}/reject", response_model=ConfirmationOut)
def reject(confirmation_id: str, db: DbSession, user: CurrentUser) -> ToolConfirmation:
    confirmation = _require(db, user, confirmation_id)
    try:
        return reject_confirmation(db, confirmation)
    except ConfirmationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _require(db: DbSession, user: CurrentUser, confirmation_id: str) -> ToolConfirmation:
    confirmation = db.get(ToolConfirmation, confirmation_id)
    if confirmation is None:
        raise HTTPException(status_code=404, detail="Not found")
    ensure_workspace_access(db, user, confirmation.workspace_id)
    return confirmation
