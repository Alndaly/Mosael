"""时间线(序列)的用例:谁看得见、看到的是什么样子、谁能建、谁能导出。剪辑本身仍走确认卡与 operations。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Project, Sequence, Track, User
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm, require_sequence_access
from app.domain.sequences.creation import create_sequence_scaffold
from app.domain.sequences.history import can_redo, can_undo


def load(db: Session, sequence_id: str) -> Sequence:
    """整条序列(轨道与片段一起取出),带上能不能撤销 / 重做。**不过闸** —— 调用方先过。"""
    sequence = db.scalar(
        select(Sequence).where(Sequence.id == sequence_id).options(selectinload(Sequence.tracks).selectinload(Track.clips))
    )
    if sequence is None:
        raise NotVisible("Sequence not found")
    sequence.can_undo = can_undo(db, sequence_id)
    sequence.can_redo = can_redo(db, sequence_id)
    return sequence


def readable(db: Session, user: User, sequence_id: str) -> Sequence:
    require_sequence_access(db, user, sequence_id)
    return load(db, sequence_id)


def latest_of_project(db: Session, user: User, project_id: str) -> Sequence | None:
    """项目里最近改过的那条序列;项目看不见就是 404。"""
    project = db.get(Project, project_id)
    if project is None:
        raise NotVisible("Not found")
    ensure_workspace_access(db, user, project.workspace_id)
    sequence_id = db.scalar(
        select(Sequence.id).where(Sequence.project_id == project_id).order_by(Sequence.updated_at.desc()).limit(1)
    )
    return load(db, sequence_id) if sequence_id else None


def revisions_of_project(db: Session, user: User, project_id: str) -> list[tuple[str, int]]:
    """项目里每条序列的 (id, revision),最近改过的在前。编辑器一直在轮询它,所以只取这两列。"""
    project = db.get(Project, project_id)
    if project is not None:
        ensure_workspace_access(db, user, project.workspace_id)
    return [
        (sequence_id, revision)
        for sequence_id, revision in db.execute(
            select(Sequence.id, Sequence.revision)
            .where(Sequence.project_id == project_id)
            .order_by(Sequence.updated_at.desc())
        )
    ]


def create(
    db: Session, user: User, workspace_id: str, project_id: str, *, name: str, width: int, height: int, fps: float
) -> Sequence:
    """项目也要在这个工作区里:只核工作区的话,能把序列塞进一个自己碰不到的项目。项目还没有当前序列就用它。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")
    project = db.get(Project, project_id)
    if project is None or project.workspace_id != workspace_id:
        raise NotVisible("Project not found in this workspace")
    sequence = create_sequence_scaffold(db, project, name=name, width=width, height=height, fps=fps).sequence
    if project.active_sequence_id is None:
        project.active_sequence_id = sequence.id
    db.flush()
    return sequence


def exportable(db: Session, user: User, sequence_id: str) -> Sequence:
    """导出、取一帧存成素材:要 `export`。"""
    return require_sequence_access(db, user, sequence_id, perm="export")
