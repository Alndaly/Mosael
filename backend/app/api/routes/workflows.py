from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response

from app.api.deps import CurrentUser, DbSession
from typing import TYPE_CHECKING

from app.api.schemas import (
    AgentSessionOut,
    JobOut,
    WorkflowAiEditRequest,
    WorkflowAiEditResponse,
    WorkflowCreate,
    WorkflowNodeTypeOut,
    WorkflowOut,
    WorkflowRunRequest,
    WorkflowUpdate,
)
from app.core.permissions import ensure_workspace_access
from app.db.models import Job, Workflow
from app.domain.workflows import (
    NODE_TYPES,
    WorkflowDomainError,
    create_workflow,
    list_workflows,
    update_workflow,
)
from app.domain.workflows.engine import start_workflow_job

if TYPE_CHECKING:
    from app.db.models import AgentSession

router = APIRouter(tags=["workflows"])


@router.get("/workflows/node-types", response_model=list[WorkflowNodeTypeOut])
def node_types() -> list[dict]:
    return [
        {
            "type": key,
            "label": meta["label"],
            "description": meta["description"],
            "config": meta["config"],
            "outputs": list(meta["outputs"]),
        }
        for key, meta in NODE_TYPES.items()
    ]


@router.get("/workflows", response_model=list[WorkflowOut])
def list_all(workspace_id: str, db: DbSession, user: CurrentUser) -> list[Workflow]:
    ensure_workspace_access(db, user, workspace_id)
    return list_workflows(db, workspace_id)


@router.post("/workflows", response_model=WorkflowOut)
def create(body: WorkflowCreate, db: DbSession, user: CurrentUser) -> Workflow:
    ensure_workspace_access(db, user, body.workspace_id)
    try:
        return create_workflow(
            db, workspace_id=body.workspace_id, name=body.name, description=body.description, graph=body.graph
        )
    except WorkflowDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/workflows/{workflow_id}", response_model=WorkflowOut)
def get_one(workflow_id: str, db: DbSession, user: CurrentUser) -> Workflow:
    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    return workflow


@router.patch("/workflows/{workflow_id}", response_model=WorkflowOut)
def update(workflow_id: str, body: WorkflowUpdate, db: DbSession, user: CurrentUser) -> Workflow:
    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    try:
        return update_workflow(db, workflow, body.model_dump(exclude_unset=True))
    except WorkflowDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/workflows/{workflow_id}", status_code=204)
def delete(workflow_id: str, db: DbSession, user: CurrentUser) -> Response:
    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    db.delete(workflow)
    db.commit()
    return Response(status_code=204)


@router.post("/workflows/{workflow_id}/run", response_model=JobOut)
def run(workflow_id: str, body: WorkflowRunRequest, db: DbSession, user: CurrentUser) -> Job:
    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    try:
        return start_workflow_job(db, workflow, params=body.params)
    except WorkflowDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/workflows/{workflow_id}/ai-edit", response_model=WorkflowAiEditResponse)
def ai_edit(workflow_id: str, body: WorkflowAiEditRequest, db: DbSession, user: CurrentUser) -> dict:
    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    from app.domain.workflows.ai_edit import ai_edit_graph

    try:
        graph, summary = ai_edit_graph(
            db,
            instruction=body.instruction,
            graph=body.graph if body.graph is not None else workflow.graph,
            profile_id=body.profile_id,
        )
    except WorkflowDomainError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"graph": graph, "summary": summary}


@router.post("/workflows/{workflow_id}/agent-session", response_model=AgentSessionOut)
def workflow_agent_session(workflow_id: str, db: DbSession, user: CurrentUser) -> "AgentSession":
    """工作流专属常驻智能体会话:按 external_key 找回,记忆随会话长期保留。"""
    workflow = _get(db, workflow_id)
    ensure_workspace_access(db, user, workflow.workspace_id)
    from sqlalchemy import select

    from app.ai.agent import host
    from app.db.models import AgentSession

    key = f"workflow:{workflow_id}"
    existing = db.scalar(select(AgentSession).where(AgentSession.external_key == key))
    if existing is not None:
        return existing
    return host.create_session(
        db,
        workspace_id=workflow.workspace_id,
        origin="workflow",
        external_key=key,
        title=f"工作流 · {workflow.name}",
    )


def _get(db: DbSession, workflow_id: str) -> Workflow:
    workflow = db.get(Workflow, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return workflow
