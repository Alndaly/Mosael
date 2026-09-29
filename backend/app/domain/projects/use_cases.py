"""项目的用例:谁能做、做什么写在一起(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。不提交事务。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Asset, Clip, Project, Sequence, Track, User
from app.domain import projects as projects_svc
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm


def readable(db: Session, user: User, project_id: str, *, perm: str | None = None) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise NotVisible("Not found")
    if perm is None:
        ensure_workspace_access(db, user, project.workspace_id)
    else:
        ensure_workspace_perm(db, user, project.workspace_id, perm)
    return project


def create(db: Session, user: User, workspace_id: str, name: str) -> Project:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    project = projects_svc.create_project(db, workspace_id, name)
    db.flush()
    return project


def rename(db: Session, user: User, project_id: str, name: str) -> Project:
    project = readable(db, user, project_id, perm="edit")
    project.name = name
    db.flush()
    return project


def delete(db: Session, user: User, project_id: str) -> None:
    db.delete(readable(db, user, project_id, perm="delete"))


def list_with_stats(db: Session, user: User, workspace_id: str) -> list[dict[str, Any]]:
    """项目卡片要的全部:素材数、序列数、时间线时长、封面、较新的「更新于」。"""
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
        dict(
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


def _covers(db: Session, projects: list[Project]) -> dict[str, str]:
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
