from fastapi import APIRouter, Query, Response

from app.api.deps import CurrentUser, DbSession, Tx
from app.api.schemas.notes import NoteAppend, NoteContent, NoteCreate, NoteOut, NotePageCreate, NoteRestore, NoteRevisionOut, NoteUpdate, NoteReferenceOut
from app.domain.agent import use_cases as agent_use_cases
from app.domain.notes import use_cases

router = APIRouter(tags=["notes"])

# 闸在 domain/notes/use_cases;这里只做 HTTP 的转译。


@router.get("/notes/sources/message/{message_id}")
def source_message(message_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    """笔记引用的一条对话消息(看得见它所在的那次对话才给,见 agent/use_cases.cited_message)。"""
    message, session_id = agent_use_cases.cited_message(db, user, workspace_id, message_id)
    return {"content": message.content, "session_id": session_id, "created_at": message.created_at}


@router.get("/notes", response_model=list[NoteOut])
def list_notes(workspace_id: str, db: DbSession, user: CurrentUser, q: str = Query("", max_length=300),
               trashed: bool = False, favorite: bool = False, topic: str = Query("", max_length=200),
               limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
    return use_cases.query(db, user, workspace_id, q, limit=limit, offset=offset, trashed=trashed, favorite=favorite,
                           topic=topic)


@router.get("/notes/topics", response_model=list[str])
def list_topics(workspace_id: str, db: DbSession, user: CurrentUser, trashed: bool = False):
    """笔记页的主题下拉。在 `/notes/{note_id}` 之前声明,否则 `topics` 会被当成一篇笔记的 id。"""
    return use_cases.topics(db, user, workspace_id, trashed=trashed)


@router.post("/notes", response_model=NoteOut)
def create(body: NoteCreate, db: Tx, user: CurrentUser):
    return use_cases.create(db, user, body.workspace_id, NoteContent.model_validate(body.model_dump()))


@router.post("/notes/from-page", response_model=NoteOut)
def create_from_page(body: NotePageCreate, db: Tx, user: CurrentUser):
    """内嵌浏览器顶栏「存成笔记」:整页正文或选中的文字,带着来源链接与页面标题(见 domain/documents/web_page)。"""
    from app.domain.documents import use_cases as documents

    return documents.save_page_as_note(
        db, user, body.workspace_id, url=body.url, title=body.title, html=body.html, selection=body.selection,
        project_id=body.project_id,
    )


@router.get("/notes/{note_id}", response_model=NoteOut)
def read(note_id: str, db: DbSession, user: CurrentUser, workspace_id: str | None = None):
    """`workspace_id` **可选** —— 笔记自带归属,和素材/工作流那两条详情路由一致。

    它此前是必填的,而引用胶囊的探活用的是同一个形状的 URL(/api/notes/{id}),于是点笔记
    胶囊永远 422 → 界面报「它已经不在了」,可它明明在。带上时仍按它查(跨工作区的 id 读不出来)。
    """
    return use_cases.read(db, user, note_id, workspace_id)


@router.get("/notes/{note_id}/reference", response_model=NoteReferenceOut)
def reference(note_id: str, workspace_id: str, db: DbSession, user: CurrentUser,
              revision: int | None = Query(None, ge=1)):
    return use_cases.reference(db, user, workspace_id, note_id, revision)


@router.patch("/notes/{note_id}", response_model=NoteOut)
def edit(note_id: str, body: NoteUpdate, db: Tx, user: CurrentUser):
    return use_cases.save(db, user, body.workspace_id, note_id, body.base_revision,
                          NoteContent.model_validate(body.model_dump()))


@router.delete("/notes/{note_id}", status_code=204)
def permanently_delete(note_id: str, workspace_id: str, db: Tx, user: CurrentUser,
                       base_revision: int = Query(ge=1)):
    use_cases.purge(db, user, workspace_id, note_id, base_revision)
    return Response(status_code=204)


@router.post("/notes/{note_id}/append", response_model=NoteOut)
def append(note_id: str, body: NoteAppend, db: Tx, user: CurrentUser):
    return use_cases.append(db, user, body.workspace_id, note_id, body.markdown, [s.model_dump() for s in body.sources])


@router.get("/notes/{note_id}/revisions", response_model=list[NoteRevisionOut])
def revisions(note_id: str, workspace_id: str, db: DbSession, user: CurrentUser):
    return use_cases.revisions(db, user, workspace_id, note_id)


@router.get("/notes/{note_id}/revisions/{revision}")
def revision_content(note_id: str, revision: int, workspace_id: str, db: DbSession, user: CurrentUser):
    row = use_cases.revision(db, user, workspace_id, note_id, revision)
    return {"note_id": note_id, "revision": row.revision, "created_at": row.created_at, **row.snapshot}


@router.post("/notes/{note_id}/restore", response_model=NoteOut)
def restore(note_id: str, body: NoteRestore, db: Tx, user: CurrentUser):
    return use_cases.restore(db, user, body.workspace_id, note_id, body.revision, body.base_revision)
