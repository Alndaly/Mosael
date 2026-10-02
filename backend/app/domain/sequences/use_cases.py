"""时间线(序列)的用例:谁看得见、看到的是什么样子、谁能建、谁能导出。剪辑本身仍走确认卡与 operations。"""

from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session, selectinload

from app.core.i18n import tr
from app.db.models import Board, Project, Sequence, Track, User
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm, require_sequence_access
from app.domain.references import referrers
from app.domain.sequences.creation import copy_sequence, create_sequence_scaffold
from app.domain.sequences.errors import SequenceDomainError
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


def rename(db: Session, user: User, sequence_id: str, name: str) -> Sequence:
    """改名。不是一次剪辑(不进撤销栈),但版本号要推一下:序列的 JSON 按 (id, revision) 缓存,
    编辑器也靠轮询版本号决定要不要重取 —— 不推的话,别人那边一直显示旧名字。"""
    sequence = require_sequence_access(db, user, sequence_id, perm="edit")
    sequence.name = name
    db.execute(update(Sequence).where(Sequence.id == sequence.id).values(revision=Sequence.revision + 1))
    db.flush()
    return sequence


def duplicate(db: Session, user: User, sequence_id: str, *, name: str | None = None) -> Sequence:
    """在同一个项目里复制一条时间线(copy_sequence:轨道、片段的全部属性;编辑历史不带过去)。"""
    source = require_sequence_access(db, user, sequence_id, perm="edit")
    project = db.get(Project, source.project_id)
    return copy_sequence(db, source, project, name=name or tr("sequenceCopyName", name=source.name))


def delete(db: Session, user: User, sequence_id: str) -> None:
    """删一条时间线。两种情况不让删,并说清楚为什么:

    · **画板上还摆着它**(时间线格):删了那一格就指着一条不存在的时间线,整张画板从此存不回去。
      点名是哪几张画板 —— 和删 3D 场景同一条规矩(domain/scenes.delete_scene)。
    · **这是项目里最后一条**:项目打开时总要停在一条时间线上;不要这个项目就删项目。

    删掉的若是项目当前打开的那条,改停在最近改过的另一条上。
    """
    sequence = require_sequence_access(db, user, sequence_id, perm="delete")
    boards = list(db.scalars(
        select(Board.name).where(Board.workspace_id == sequence.workspace_id,
                                 Board.id.in_(referrers("sequence", sequence.id, "board")))
    ))
    if boards:
        raise SequenceDomainError("seqErr_sequenceOnBoards", names="、".join(sorted(boards)))
    next_active = db.scalar(
        select(Sequence.id)
        .where(Sequence.project_id == sequence.project_id, Sequence.id != sequence.id)
        .order_by(Sequence.updated_at.desc())
        .limit(1)
    )
    if next_active is None:
        raise SequenceDomainError("seqErr_lastSequence")
    project = db.get(Project, sequence.project_id)
    if project is not None and project.active_sequence_id == sequence.id:
        project.active_sequence_id = next_active
    db.delete(sequence)
    db.flush()
