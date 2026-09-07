"""Writing with immutable revisions and workspace-scoped source references.

**为什么抛领域异常而不是 HTTPException**:笔记不只从路由进来 —— 画板保存要校验它引用的
文档、工作流的知识节点要读它、智能体工具也会写它。领域层抛 FastAPI 的异常,这些非 HTTP 的
调用方就得反过来 catch HTTPException 再翻回自己的领域错误,而那正是此前 `domain/boards.py`
和 `workflows/executors/knowledge.py` 在做的事。

状态码由边界统一翻(见 main.py 的异常处理器),每个子类各对应一个**故意的**答案。
与 `domain/permissions` 同构。
"""
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.domain.note_types import NoteContent
from app.db.models import Asset, AgentMessage, AgentSession, Board, Note, NoteRevision, Project
from app.db.model_base import now


class NoteDomainError(ValueError):
    """笔记领域说不行。`status` 由子类给,边界照着翻(见 main.py)。"""

    status = 422


class NoteNotFound(NoteDomainError):
    """要么真的不存在,要么不属于这个工作区 —— 两种情况**同一个答案**。
    分开答等于告诉外人"这个 id 是存在的"。"""

    status = 404


class NoteConflict(NoteDomainError):
    """笔记在,但当前状态下这件事做不了:修订号对不上、或者它在回收站里。"""

    status = 409


FIELDS = tuple(NoteContent.model_fields)


def get_note(db: Session, workspace_id: str, note_id: str) -> Note:
    note = db.scalar(select(Note).where(Note.id == note_id, Note.workspace_id == workspace_id))
    if note is None:
        raise NoteNotFound("笔记不存在")
    return note


def snapshot(note: Note) -> dict:
    return {key: getattr(note, key) for key in FIELDS}


def validate_content(db: Session, workspace_id: str, content: NoteContent, existing_sources: list[dict] | None = None) -> dict:
    data = content.model_dump()
    data["title"] = data["title"].strip()
    for key in ("tags", "topics"):
        data[key] = list(dict.fromkeys(s.strip() for s in data[key] if s.strip()))
        if any(len(s) > 80 for s in data[key]):
            raise NoteDomainError("标签或专题名称不能超过 80 字")
    if data["project_id"]:
        project = db.get(Project, data["project_id"])
        if project is None or project.workspace_id != workspace_id:
            raise NoteNotFound("项目不存在")
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
            raise NoteNotFound("引用来源不存在于当前工作区")
        if kind == "note":
            if obj.trashed:
                raise NoteConflict("引用的笔记已在回收站")
            source["revision"] = source["revision"] or obj.revision
            if db.get(NoteRevision, (key, source["revision"])) is None:
                raise NoteNotFound("引用版本不存在")
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
        raise NoteConflict("笔记已被其他操作更新，请保留草稿并重新载入")
    data = validate_content(db, workspace_id, content, note.sources + (restored_sources or []))
    if data == snapshot(note):
        return note
    # Compare-and-swap also catches two requests that read the same revision concurrently.
    result = db.execute(update(Note).where(Note.id == note_id, Note.revision == base_revision).values(
        **data, revision=base_revision + 1, updated_at=now(),
    ), execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        db.rollback()
        raise NoteConflict("笔记已被其他操作更新，请保留草稿并重新载入")
    db.add(NoteRevision(note_id=note_id, revision=base_revision + 1, snapshot=data))
    db.commit()
    db.refresh(note)
    return note


#: 追加撞上并发写入时重读当前修订再试几次。冲突只可能来自"另一次写入刚落地",
#: 重读就能解决;给上限只是不在病态争用下无限打转。
#: 追加的内容与原文之间用它隔开。**前端按同一个串认出"这次改动是纯追加"**,从而把
#: 后台追加并进正在编辑的草稿而不打断打字 —— 见 contracts/shared-constants.json。
APPEND_SEPARATOR = "\n\n"

APPEND_RETRIES = 4


def append_note(db: Session, workspace_id: str, note_id: str, markdown: str,
                sources: list[dict]) -> Note:
    """把一段内容追加到笔记末尾。

    **不拿调用方的 base_revision 做条件更新。** 追加到末尾与文档别处的编辑可交换,而调用方
    手里的修订号往往来自一次列表查询,早就旧了 —— 用它做 CAS,只会把两件本可并存的事判成
    冲突,然后让正在打字的那个人吃 409。

    写入本身仍然是 CAS 的(`save_note` 内部那条条件 UPDATE 一步没少),只是基准取**服务端
    当前修订**:撞上真正的并发写就重读再追加,而不是把冲突推给用户。
    """
    for attempt in range(APPEND_RETRIES):
        note = get_note(db, workspace_id, note_id)
        if note.trashed:
            raise NoteConflict("请先从回收站恢复笔记")
        data = snapshot(note)
        data["markdown"] = APPEND_SEPARATOR.join(filter(None, [note.markdown, markdown]))
        data["sources"] = note.sources + sources
        try:
            return save_note(db, workspace_id, note_id, note.revision,
                             NoteContent.model_validate(data))
        except NoteConflict:
            # 只可能是修订号对不上:读到写之间有人抢先落地了一版,重读再追加就好。
            # 「在回收站里」同样是 NoteConflict,但它在 try 之外就抛掉了 —— 那种重试
            # 一万次也还在回收站。
            if attempt == APPEND_RETRIES - 1:
                raise
    raise AssertionError("unreachable")  # pragma: no cover


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
        raise NoteConflict("引用的笔记已在回收站，请先恢复笔记")
    version = note.revision if revision is None else revision
    row = db.get(NoteRevision, (note.id, version))
    if row is None:
        raise NoteNotFound("引用版本不存在")
    return {"note_id": note.id, "revision": version, "title": row.snapshot["title"],
            "markdown": row.snapshot["markdown"], "tags": row.snapshot["tags"],
            "citation_url": f"#/notes?note={quote(note.id)}&revision={version}"}
