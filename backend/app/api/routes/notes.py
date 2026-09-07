from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import select, delete

from app.api.deps import CurrentUser, DbSession
from app.api.schemas.notes import NoteAppend, NoteContent, NoteCreate, NoteOut, NoteRestore, NoteUpdate, NoteReferenceOut
from app.db.models import AgentMessage, AgentSession, Note, NoteRevision
from app.domain.notes import append_note, create_note, get_note, save_note, read_reference, query_notes
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm

router = APIRouter(tags=["notes"])


@router.get("/notes/sources/message/{message_id}")
def source_message(message_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, workspace_id)
    message = db.get(AgentMessage, message_id)
    session = db.get(AgentSession, message.session_id) if message else None
    if session is None or session.workspace_id != workspace_id:
        raise HTTPException(404, "来源不存在")
    return {"content": message.content, "session_id": session.id, "created_at": message.created_at}


@router.get("/notes", response_model=list[NoteOut])
def list_notes(workspace_id: str, db: DbSession, user: CurrentUser, q: str = Query("", max_length=300),
               trashed: bool = False, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    ensure_workspace_access(db, user, workspace_id)
    return query_notes(db, workspace_id, q, limit=limit, offset=offset, trashed=trashed)


@router.post("/notes", response_model=NoteOut)
def create(body: NoteCreate, db: DbSession, user: CurrentUser):
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    return create_note(db, body.workspace_id, NoteContent.model_validate(body.model_dump()))


@router.get("/notes/{note_id}", response_model=NoteOut)
def read(note_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, workspace_id)
    return get_note(db, workspace_id, note_id)


@router.get("/notes/{note_id}/reference", response_model=NoteReferenceOut)
def reference(note_id: str, workspace_id: str, db: DbSession, user: CurrentUser,
              revision: int | None = Query(None, ge=1)):
    ensure_workspace_access(db, user, workspace_id)
    return read_reference(db, workspace_id, note_id, revision)


@router.patch("/notes/{note_id}", response_model=NoteOut)
def edit(note_id: str, body: NoteUpdate, db: DbSession, user: CurrentUser):
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    return save_note(db, body.workspace_id, note_id, body.base_revision, NoteContent.model_validate(body.model_dump()))


@router.delete("/notes/{note_id}", status_code=204)
def permanently_delete(note_id: str, workspace_id: str, db: DbSession, user: CurrentUser,
                       base_revision: int = Query(ge=1)):
    ensure_workspace_perm(db, user, workspace_id, "edit")
    note = get_note(db, workspace_id, note_id)
    if not note.trashed:
        raise HTTPException(409, "请先将笔记移入回收站")
    result = db.execute(delete(Note).where(Note.id == note_id, Note.workspace_id == workspace_id,
                                         Note.trashed.is_(True), Note.revision == base_revision))
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(409, "笔记状态已变化，请重新载入后再删除")
    db.commit()
    return Response(status_code=204)


@router.post("/notes/{note_id}/append", response_model=NoteOut)
def append(note_id: str, body: NoteAppend, db: DbSession, user: CurrentUser):
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    return append_note(db, body.workspace_id, note_id, body.markdown,
                       [s.model_dump() for s in body.sources])


@router.get("/notes/{note_id}/revisions")
def revisions(note_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, workspace_id)
    get_note(db, workspace_id, note_id)
    rows = db.scalars(select(NoteRevision).where(NoteRevision.note_id == note_id).order_by(NoteRevision.revision.desc()).limit(100))
    return [{"revision": r.revision, "created_at": r.created_at, "title": r.snapshot["title"]} for r in rows]


@router.get("/notes/{note_id}/revisions/{revision}")
def revision_content(note_id: str, revision: int, workspace_id: str, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, workspace_id)
    get_note(db, workspace_id, note_id)
    row = db.get(NoteRevision, (note_id, revision))
    if row is None:
        raise HTTPException(404, "版本不存在")
    return {"note_id": note_id, "revision": row.revision, "created_at": row.created_at, **row.snapshot}


@router.post("/notes/{note_id}/restore", response_model=NoteOut)
def restore(note_id: str, body: NoteRestore, db: DbSession, user: CurrentUser):
    ensure_workspace_perm(db, user, body.workspace_id, "edit")
    get_note(db, body.workspace_id, note_id)
    row = db.get(NoteRevision, (note_id, body.revision))
    if row is None:
        raise HTTPException(404, "版本不存在")
    return save_note(db, body.workspace_id, note_id, body.base_revision, NoteContent.model_validate(row.snapshot),
                     restored_sources=row.snapshot["sources"])
