from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import BatchCreate, BatchOut
from app.core.permissions import ensure_workspace_access
from app.db.models import BatchRun, Workflow
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.batch import batch_with_items, start_batch

router = APIRouter(tags=["batches"])


@router.post("/batches", response_model=BatchOut)
def create(body: BatchCreate, db: DbSession, user: CurrentUser) -> dict:
    ensure_workspace_access(db, user, body.workspace_id)
    workflow = db.get(Workflow, body.workflow_id)
    if workflow is None or workflow.workspace_id != body.workspace_id:
        raise HTTPException(status_code=404, detail="Workflow not found in this workspace")
    try:
        batch = start_batch(
            db, workspace_id=body.workspace_id, workflow=workflow, name=body.name, params_list=body.params_list
        )
    except WorkflowDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return batch_with_items(db, batch)


@router.get("/batches", response_model=list[BatchOut])
def list_all(workspace_id: str, db: DbSession, user: CurrentUser) -> list[dict]:
    ensure_workspace_access(db, user, workspace_id)
    batches = db.scalars(
        select(BatchRun).where(BatchRun.workspace_id == workspace_id).order_by(BatchRun.created_at.desc())
    ).all()
    return [batch_with_items(db, batch) for batch in batches]


@router.get("/batches/{batch_id}", response_model=BatchOut)
def get_one(batch_id: str, db: DbSession, user: CurrentUser) -> dict:
    batch = _get(db, batch_id)
    ensure_workspace_access(db, user, batch.workspace_id)
    return batch_with_items(db, batch)


@router.delete("/batches/{batch_id}", status_code=204)
def delete(batch_id: str, db: DbSession, user: CurrentUser) -> Response:
    batch = _get(db, batch_id)
    ensure_workspace_access(db, user, batch.workspace_id)
    db.delete(batch)
    db.commit()
    return Response(status_code=204)


def _get(db: DbSession, batch_id: str) -> BatchRun:
    batch = db.get(BatchRun, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Batch not found")
    return batch
