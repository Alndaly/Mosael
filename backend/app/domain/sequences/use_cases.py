"""时间线(序列)的读用例:谁看得见、看到的是什么样子。写操作(剪辑)仍走确认卡与 operations。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Project, Sequence, Track, User
from app.domain.permissions import NotVisible, ensure_workspace_access, require_sequence_access
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
