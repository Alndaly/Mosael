"""Writing with immutable revisions and workspace-scoped source references."""
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.domain.note_types import NoteContent
from app.db.models import Asset, AgentMessage, AgentSession, Board, Note, NoteRevision, Project
from app.db.model_base import now


FIELDS = tuple(NoteContent.model_fields)


def get_note(db: Session, workspace_id: str, note_id: str) -> Note:
    note = db.scalar(select(Note).where(Note.id == note_id, Note.workspace_id == workspace_id))
    if note is None:
        raise HTTPException(404, "笔记不存在")
    return note


def snapshot(note: Note) -> dict:
    return {key: getattr(note, key) for key in FIELDS}


def validate_content(db: Session, workspace_id: str, content: NoteContent, existing_sources: list[dict] | None = None) -> dict:
    data = content.model_dump()
    data["title"] = data["title"].strip()
    for key in ("tags", "topics"):
        data[key] = list(dict.fromkeys(s.strip() for s in data[key] if s.strip()))
        if any(len(s) > 80 for s in data[key]):
            raise HTTPException(422, "标签或专题名称不能超过 80 字")
    if data["project_id"]:
        project = db.get(Project, data["project_id"])
        if project is None or project.workspace_id != workspace_id:
            raise HTTPException(404, "项目不存在")
    for source in data["sources"]:
        # Keep previously validated provenance even when its original is later removed.
        # Only exact stored references qualify; new/edited sources still require access.
        if source in (existing_sources or []):
            continue
        kind, key = source["kind"], source["id"]
        if kind == "url":
            continue
        if kind == "message":
            message = db.get(AgentMessage, key)
            obj = db.get(AgentSession, message.session_id) if message else None
        else:
            obj = db.get({"asset": Asset, "board": Board, "note": Note}[kind], key)
        if obj is None or obj.workspace_id != workspace_id:
            raise HTTPException(404, "引用来源不存在于当前工作区")
        if kind == "note":
            if obj.trashed:
                raise HTTPException(409, "引用的笔记已在回收站")
            source["revision"] = source["revision"] or obj.revision
            if db.get(NoteRevision, (key, source["revision"])) is None:
                raise HTTPException(404, "引用版本不存在")
    return data


def create_note(db: Session, workspace_id: str, content: NoteContent) -> Note:
    note = Note(workspace_id=workspace_id, **validate_content(db, workspace_id, content))
    db.add(note)
    db.flush()
    db.add(NoteRevision(note_id=note.id, revision=note.revision, snapshot=snapshot(note)))
    db.commit()
    db.refresh(note)
    return note


def save_note(db: Session, workspace_id: str, note_id: str, base_revision: int, content: NoteContent,
              restored_sources: list[dict] | None = None) -> Note:
    note = get_note(db, workspace_id, note_id)
    if note.revision != base_revision:
        raise HTTPException(409, "笔记已被其他操作更新，请保留草稿并重新载入")
    data = validate_content(db, workspace_id, content, note.sources + (restored_sources or []))
    if data == snapshot(note):
        return note
    # Compare-and-swap also catches two requests that read the same revision concurrently.
    result = db.execute(update(Note).where(Note.id == note_id, Note.revision == base_revision).values(
        **data, revision=base_revision + 1, updated_at=now(),
    ), execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "笔记已被其他操作更新，请保留草稿并重新载入")
    db.add(NoteRevision(note_id=note_id, revision=base_revision + 1, snapshot=data))
    db.commit()
    db.refresh(note)
    return note


def query_notes(db: Session, workspace_id: str, query: str = "", *, limit: int = 20, offset: int = 0, trashed: bool = False) -> list[Note]:
    """Literal, workspace-scoped knowledge lookup; excludes the recycle bin."""
    import json
    from sqlalchemy import or_, cast, String
    stmt = select(Note).where(Note.workspace_id == workspace_id, Note.trashed == trashed)
    for term in query.strip().split():
        escaped = json.dumps(term, ensure_ascii=True)[1:-1]
        stmt = stmt.where(or_(Note.title.icontains(term, autoescape=True), Note.markdown.icontains(term, autoescape=True),
                              *(cast(column, String).icontains(value, autoescape=True)
                                for column in (Note.tags, Note.topics) for value in (term, escaped))))
    return list(db.scalars(stmt.order_by(Note.updated_at.desc(), Note.id).offset(offset).limit(limit)))


def read_reference(db: Session, workspace_id: str, note_id: str, revision: int | None = None) -> dict:
    """Resolve a source only after checking workspace and recycle-bin state."""
    from urllib.parse import quote
    note = get_note(db, workspace_id, note_id)
    if note.trashed:
        raise HTTPException(409, "引用的笔记已在回收站，请先恢复笔记")
    version = note.revision if revision is None else revision
    row = db.get(NoteRevision, (note.id, version))
    if row is None:
        raise HTTPException(404, "引用版本不存在")
    return {"note_id": note.id, "revision": version, "title": row.snapshot["title"],
            "markdown": row.snapshot["markdown"], "tags": row.snapshot["tags"],
            "citation_url": f"#/notes?note={quote(note.id)}&revision={version}"}
