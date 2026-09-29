from __future__ import annotations

from fastapi import APIRouter, Response

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas import ProjectCreate, ProjectOut, ProjectWithStatsOut, RenameRequest
from app.db.models import Project
from app.domain.projects import use_cases

router = APIRouter(tags=["projects"])

# 闸在 domain/projects/use_cases;这里只做 HTTP 的转译。


@router.post("/projects", response_model=ProjectOut)
def create_project(body: ProjectCreate, db: Tx, user: CurrentUser) -> Project:
    return use_cases.create(db, user, body.workspace_id, body.name)


@router.get("/projects", response_model=list[ProjectWithStatsOut])
def list_projects(workspace_id: str, db: DbSession, user: CurrentUser) -> list[ProjectWithStatsOut]:
    return [ProjectWithStatsOut(**row) for row in use_cases.list_with_stats(db, user, workspace_id)]


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def rename_project(project_id: str, body: RenameRequest, db: Tx, user: CurrentUser) -> Project:
    return use_cases.rename(db, user, project_id, body.name)


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, db: Tx, user: CurrentUser) -> Response:
    use_cases.delete(db, user, project_id)
    return Response(status_code=204)
