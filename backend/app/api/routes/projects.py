from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession
from app.api.schemas import ProjectCreate, ProjectOut, ProjectWithStatsOut, RenameRequest, WorkspaceCreate, WorkspaceOut
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import Asset, Clip, Project, Sequence, Track, Workspace, WorkspaceMember

router = APIRouter(tags=["projects"])


@router.post("/workspaces", response_model=WorkspaceOut)
def create_workspace(body: WorkspaceCreate, db: DbSession, user: CurrentUser) -> WorkspaceOut:
    workspace = Workspace(name=body.name)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db.commit()
    db.refresh(workspace)
    return WorkspaceOut(id=workspace.id, name=workspace.name, role="owner")


@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(db: DbSession, user: CurrentUser) -> list[WorkspaceOut]:
    rows = db.execute(
        select(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(WorkspaceMember.user_id == user.id)
        .order_by(Workspace.created_at.desc())
    ).all()
    return [WorkspaceOut(id=ws.id, name=ws.name, role=role) for ws, role in rows]


@router.post("/projects", response_model=ProjectOut)
def create_project(body: ProjectCreate, db: DbSession, user: CurrentUser) -> Project:
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    project = Project(workspace_id=body.workspace_id, name=body.name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectWithStatsOut])
def list_projects(workspace_id: str, db: DbSession, user: CurrentUser) -> list[ProjectWithStatsOut]:
    ensure_workspace_access(db, user, workspace_id)
    projects = list(
        db.scalars(select(Project).where(Project.workspace_id == workspace_id).order_by(Project.updated_at.desc()))
    )
    if not projects:
        return []
    ids = [p.id for p in projects]

    asset_counts = dict(
        db.execute(
            select(Asset.project_id, func.count(Asset.id)).where(Asset.project_id.in_(ids)).group_by(Asset.project_id)
        ).all()
    )
    sequence_counts = dict(
        db.execute(
            select(Sequence.project_id, func.count(Sequence.id))
            .where(Sequence.project_id.in_(ids))
            .group_by(Sequence.project_id)
        ).all()
    )
    # 剪辑操作只更新 Sequence.updated_at;卡片上的「更新于」取两者较新。
    sequence_updates = dict(
        db.execute(
            select(Sequence.project_id, func.max(Sequence.updated_at))
            .where(Sequence.project_id.in_(ids))
            .group_by(Sequence.project_id)
        ).all()
    )
    # 项目时间线时长 = 该项目所有序列中最晚的 clip 结束时刻。
    durations = dict(
        db.execute(
            select(
                Sequence.project_id,
                func.max(Clip.timeline_start + (Clip.src_out - Clip.src_in) / Clip.speed),
            )
            .join(Track, Track.sequence_id == Sequence.id)
            .join(Clip, Clip.track_id == Track.id)
            .where(Sequence.project_id.in_(ids))
            .group_by(Sequence.project_id)
        ).all()
    )

    covers = _covers(db, projects)

    return [
        ProjectWithStatsOut(
            id=p.id,
            workspace_id=p.workspace_id,
            name=p.name,
            active_sequence_id=p.active_sequence_id,
            asset_count=asset_counts.get(p.id, 0),
            sequence_count=sequence_counts.get(p.id, 0),
            timeline_duration=float(durations.get(p.id) or 0.0),
            cover_asset_id=covers.get(p.id),
            created_at=p.created_at,
            updated_at=max(filter(None, [p.updated_at, sequence_updates.get(p.id)])),
        )
        for p in projects
    ]


_VISUAL = ("image", "video")


def _covers(db: DbSession, projects: list[Project]) -> dict[str, str]:
    """每个项目卡片的封面:**时间线上最早出现的那个画面**。

    此前封面由前端从「归属这个项目的素材」里挑第一张 —— 可时间线上的片段常常引用工作区里
    别处的素材(从别的项目、素材库拖进来的),于是时间线第一帧明明有图,卡片却显示
    「等待你的第一个画面」。

    看的是当前序列(没有就取最近改过的那一条);时间线上还没有画面时,才退到项目自己的
    第一张图 / 第一段视频。
    """
    ids = [p.id for p in projects]
    active = {p.id: p.active_sequence_id for p in projects}
    rows = db.execute(
        select(Sequence.project_id, Sequence.id, Sequence.updated_at, Clip.asset_id)
        .join(Clip, Clip.sequence_id == Sequence.id)
        .join(Track, Track.id == Clip.track_id)
        .join(Asset, Asset.id == Clip.asset_id)
        .where(Sequence.project_id.in_(ids), Asset.kind.in_(_VISUAL))
        .order_by(Clip.timeline_start, Track.position)
    ).all()
    first_by_sequence: dict[str, str] = {}
    latest: dict[str, tuple] = {}
    for project_id, sequence_id, updated_at, asset_id in rows:
        first_by_sequence.setdefault(sequence_id, asset_id)
        if project_id not in latest or updated_at > latest[project_id][0]:
            latest[project_id] = (updated_at, sequence_id)
    covers: dict[str, str] = {}
    for project_id in ids:
        sequence_id = active[project_id] if active[project_id] in first_by_sequence else latest.get(project_id, (None, None))[1]
        if sequence_id:
            covers[project_id] = first_by_sequence[sequence_id]
    missing = [pid for pid in ids if pid not in covers]
    if missing:
        for project_id, asset_id in db.execute(
            select(Asset.project_id, Asset.id)
            .where(Asset.project_id.in_(missing), Asset.kind.in_(_VISUAL))
            .order_by(Asset.created_at)
        ).all():
            covers.setdefault(project_id, asset_id)
    return covers


@router.patch("/projects/{project_id}", response_model=ProjectOut)
def rename_project(project_id: str, body: RenameRequest, db: DbSession, user: CurrentUser) -> Project:
    project = _require_project(db, user, project_id)
    ensure_workspace_perm(db, user, project.workspace_id, "edit")
    project.name = body.name
    db.commit()
    db.refresh(project)
    return project


@router.delete("/projects/{project_id}", status_code=204)
def delete_project(project_id: str, db: DbSession, user: CurrentUser) -> Response:
    project = _require_project(db, user, project_id)
    ensure_workspace_perm(db, user, project.workspace_id, "delete")
    db.delete(project)
    db.commit()
    return Response(status_code=204)


def _require_project(db: DbSession, user: CurrentUser, project_id: str, *, perm: str | None = None) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Not found")
    if perm is None:
        ensure_workspace_access(db, user, project.workspace_id)
    else:
        ensure_workspace_perm(db, user, project.workspace_id, perm)
    return project
