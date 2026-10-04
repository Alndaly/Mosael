"""笔记的用例:按工作区过闸,再交给 notes 本体(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

读不点名权限;写(新建、保存、追加、恢复、彻底删除)点名 edit。HTTP 路由和智能体工具调同一个函数。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Note, NoteRevision, User
from app.domain import notes
from app.domain.note_types import NoteContent, NoteRevisionOrigin
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
    rows = db.execute(
        select(NoteRevision, User.display_name, User.username)
        .outerjoin(User, User.id == NoteRevision.created_by)
        .where(NoteRevision.note_id == note_id)
        .order_by(NoteRevision.revision.desc())
        .limit(100)
    )
    return [
        {"revision": r.revision, "created_at": r.created_at, "title": r.snapshot["title"], "origin": r.origin,
         "created_by": r.created_by, "created_by_name": display_name or username or "", "restored_from": r.restored_from}
        for r, display_name, username in rows
    ]


def revision(db: Session, user: User, workspace_id: str, note_id: str, number: int) -> NoteRevision:
    read(db, user, note_id, workspace_id)
    row = db.get(NoteRevision, (note_id, number))
    if row is None:
        raise NotVisible("routeErr_noteVersionNotFound")
    return row


# ---------------- 写 ----------------


def create(db: Session, user: User, workspace_id: str, content: NoteContent, *,
           origin: NoteRevisionOrigin = "create") -> Note:
    """`origin`:页面上新建是 create;智能体经工具建的(mcp_server.create_note)传 agent。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return notes.create_note(db, workspace_id, content, actor=user.id, origin=origin)


def save(db: Session, user: User, workspace_id: str, note_id: str, base_revision: int, content: NoteContent) -> Note:
    """编辑器里的保存。智能体不走这里改正文 —— 它走改笔记的确认卡(agent/confirmable/notes)。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return notes.save_note(db, workspace_id, note_id, base_revision, content, actor=user.id, origin="edit")


def append(
    db: Session, user: User, workspace_id: str, note_id: str, markdown: str, sources: list[dict[str, Any]], *,
    origin: NoteRevisionOrigin = "append",
) -> Note:
    """`origin`:页面上「存到笔记」是 append;智能体经工具追加的(mcp_server.append_note)传 agent。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return notes.append_note(db, workspace_id, note_id, markdown, sources, actor=user.id, origin=origin)


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
        actor=user.id, origin="restore", restored_from=number, restored_sources=row.snapshot["sources"],
    )
