"""笔记的用例:按工作区过闸,再交给 notes 本体(见 CONVENTIONS「一次用例一个事务,授权在领域里」)。

读不点名权限;写(新建、保存、追加、恢复、彻底删除)点名 edit。HTTP 路由和智能体工具调同一个函数。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, literal, select
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


#: 版本记录最多列多少组;展开一组最多列多少版。
REVISION_GROUPS = 100
GROUP_REVISIONS = 200


def revisions(db: Session, user: User, workspace_id: str, note_id: str, group: int | None = None) -> list[dict[str, Any]]:
    """版本记录:一组一项(那一组最新的一版);带 `group`(那一组第一版的号)时列那一组里的每一版。

    只取标题,不把每一版的整篇快照搬出来 —— 一组一项也可能是上百版里挑出来的。
    """
    read(db, user, note_id, workspace_id)
    columns = (
        NoteRevision.revision, NoteRevision.created_at, func.json_extract(NoteRevision.snapshot, "$.title").label("title"),
        NoteRevision.origin, NoteRevision.created_by, NoteRevision.restored_from, NoteRevision.group_start,
        NoteRevision.chars_added, NoteRevision.chars_removed, NoteRevision.title_changed,
        User.display_name, User.username,
    )
    if group is None:
        last = (
            select(NoteRevision.group_start, func.max(NoteRevision.revision).label("last"), func.count().label("saves"),
                   func.min(NoteRevision.created_at).label("started_at"))
            .where(NoteRevision.note_id == note_id)
            .group_by(NoteRevision.group_start)
            .order_by(NoteRevision.group_start.desc())
            .limit(REVISION_GROUPS)
            .subquery()
        )
        stmt = select(*columns, last.c.saves, last.c.started_at).join(
            last, and_(NoteRevision.note_id == note_id, NoteRevision.revision == last.c.last)
        )
    else:
        stmt = (
            select(*columns, literal(1).label("saves"), NoteRevision.created_at.label("started_at"))
            .where(NoteRevision.note_id == note_id, NoteRevision.group_start == group)
            .limit(GROUP_REVISIONS)
        )
    rows = db.execute(stmt.outerjoin(User, User.id == NoteRevision.created_by).order_by(NoteRevision.revision.desc()))
    return [
        {**row._asdict(), "title": row.title or "", "created_by_name": row.display_name or row.username or ""}
        for row in rows
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


def save(db: Session, user: User, workspace_id: str, note_id: str, base_save_seq: int, content: NoteContent) -> Note:
    """编辑器里的保存。智能体不走这里改正文 —— 它走改笔记的确认卡(agent/confirmable/notes)。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return notes.save_note(db, workspace_id, note_id, base_save_seq, content, actor=user.id, origin="edit")


def append(
    db: Session, user: User, workspace_id: str, note_id: str, markdown: str, sources: list[dict[str, Any]], *,
    origin: NoteRevisionOrigin = "append",
) -> Note:
    """`origin`:页面上「存到笔记」是 append;智能体经工具追加的(mcp_server.append_note)传 agent。"""
    ensure_workspace_perm(db, user, workspace_id, "edit")
    return notes.append_note(db, workspace_id, note_id, markdown, sources, actor=user.id, origin=origin)


def purge(db: Session, user: User, workspace_id: str, note_id: str, base_save_seq: int) -> None:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    notes.purge_note(db, workspace_id, note_id, base_save_seq)


def restore(db: Session, user: User, workspace_id: str, note_id: str, number: int, base_save_seq: int) -> Note:
    ensure_workspace_perm(db, user, workspace_id, "edit")
    notes.get_note(db, workspace_id, note_id)
    row = db.get(NoteRevision, (note_id, number))
    if row is None:
        raise NotVisible("routeErr_noteVersionNotFound")
    return notes.save_note(
        db, workspace_id, note_id, base_save_seq, NoteContent.model_validate(row.snapshot),
        actor=user.id, origin="restore", restored_from=number, restored_sources=row.snapshot["sources"],
    )
