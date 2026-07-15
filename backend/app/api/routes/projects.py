from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import ProjectCreate, ProjectOut, WorkspaceCreate, WorkspaceOut
from app.core.permissions import ensure_workspace_access
from app.db.models import Project, Workspace, WorkspaceMember

router = APIRouter(tags=["projects"])


@router.post("/workspaces", response_model=WorkspaceOut)
def create_workspace(body: WorkspaceCreate, db: DbSession, user: CurrentUser) -> Workspace:
    workspace = Workspace(name=body.name)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db.commit()
    db.refresh(workspace)
    return workspace


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(db: DbSession, user: CurrentUser) -> list[Workspace]:
    stmt = (
        select(Workspace)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(Workspace.created_at.desc())
    )
    return list(db.scalars(stmt))


@router.post("/projects", response_model=ProjectOut)
def create_project(body: ProjectCreate, db: DbSession, user: CurrentUser) -> Project:
    ensure_workspace_access(db, user, body.workspace_id)
    project = Project(workspace_id=body.workspace_id, name=body.name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(workspace_id: str, db: DbSession, user: CurrentUser) -> list[Project]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(Project).where(Project.workspace_id == workspace_id).order_by(Project.updated_at.desc())
    return list(db.scalars(stmt))
