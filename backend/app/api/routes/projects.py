from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from app.api.deps import DbSession
from app.api.schemas import ProjectCreate, ProjectOut, WorkspaceCreate, WorkspaceOut
from app.db.models import Project, Workspace

router = APIRouter(tags=["projects"])


@router.post("/workspaces", response_model=WorkspaceOut)
def create_workspace(body: WorkspaceCreate, db: DbSession) -> Workspace:
    workspace = Workspace(name=body.name)
    db.add(workspace)
    db.commit()
    db.refresh(workspace)
    return workspace


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(db: DbSession) -> list[Workspace]:
    return list(db.scalars(select(Workspace).order_by(Workspace.created_at.desc())))


@router.post("/projects", response_model=ProjectOut)
def create_project(body: ProjectCreate, db: DbSession) -> Project:
    project = Project(workspace_id=body.workspace_id, name=body.name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(workspace_id: str, db: DbSession) -> list[Project]:
    stmt = select(Project).where(Project.workspace_id == workspace_id).order_by(Project.updated_at.desc())
    return list(db.scalars(stmt))

