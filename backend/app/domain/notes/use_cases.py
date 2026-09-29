"""笔记的用例:按工作区过闸,再交给 notes 本体(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

读不点名权限;写(新建、保存、追加、恢复、彻底删除)点名 edit。HTTP 路由和智能体工具调同一个函数。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Note, NoteRevision, User
from app.domain import notes
from app.domain.note_types import NoteContent
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm, owning_workspace


# ---------------- 读 ----------------


def query(db: Session, user: User, workspace_id: str, text: str = "", **filters: Any) -> list[Note]:
    ensure_workspace_access(db, user, workspace_id)
    return notes.query_notes(db, workspace_id, text, **filters)


def topics(db: Session, user: User, workspace_id: str, *, trashed: bool = False) -> list[str]:
    ensure_workspace_access(db, user, workspace_id)
    return notes.note_topics(db, workspace_id, trashed=trashed)


def read(db: Session, user: User, note_id: str, workspace_id: str | None = None) -> Note:
    """`workspace_id` 可选 —— 笔记自带归属;带上时仍按它查(跨工作区的 id 读不出来)。"""
    workspace_id = workspace_id or owning_workspace(db, Note, note_id)
    ensure_workspace_access(db, user, workspace_id)
    return notes.get_note(db, workspace_id, note_id)


def reference(db: Session, user: User, workspace_id: str, note_id: str, revision: int | None) -> Any:
    ensure_workspace_access(db, user, workspace_id)
    return notes.read_reference(db, workspace_id, note_id, revision)


def revisions(db: Session, user: User, workspace_id: str, note_id: str) -> list[dict[str, Any]]:
    read(db, user, note_id, workspace_id)
    rows = db.scalars(select(NoteRevision).where(NoteRevision.note_id == note_id).order_by(NoteRevision.revision.desc()).limit(100))
    return [{"revision": r.revision, "created_at": r.created_at, "title": r.snapshot["title"]} for r in rows]


def revision(db: Session, user: User, workspace_id: str, note_id: str, number: int) -> NoteRevision:
    read(db, user, note_id, workspace_id)
    row = db.get(NoteRevision, (note_id, number))
    if row is None:
        raise NotVisible("routeErr_noteVersionNotFound")
    return row


# ---------------- 写 ----------------


def create(db: Session, user: User, workspace_id: str, content: NoteContent) -> Note:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return notes.create_note(db, workspace_id, content, actor=user.id)


def save(db: Session, user: User, workspace_id: str, note_id: str, base_revision: int, content: NoteContent) -> Note:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return notes.save_note(db, workspace_id, note_id, base_revision, content, actor=user.id)


def append(
    db: Session, user: User, workspace_id: str, note_id: str, markdown: str, sources: list[dict[str, Any]]
) -> Note:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return notes.append_note(db, workspace_id, note_id, markdown, sources, actor=user.id)


def purge(db: Session, user: User, workspace_id: str, note_id: str, base_revision: int) -> None:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    notes.purge_note(db, workspace_id, note_id, base_revision)


def restore(db: Session, user: User, workspace_id: str, note_id: str, number: int, base_revision: int) -> Note:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    notes.get_note(db, workspace_id, note_id)
    row = db.get(NoteRevision, (note_id, number))
    if row is None:
        raise NotVisible("routeErr_noteVersionNotFound")
    return notes.save_note(
        db, workspace_id, note_id, base_revision, NoteContent.model_validate(row.snapshot),
        actor=user.id, restored_sources=row.snapshot["sources"],
    )
