"""Writing with immutable revisions and workspace-scoped source references.

**为什么抛领域异常而不是 HTTPException**:笔记不只从路由进来 —— 画板保存要校验它引用的
文档、工作流的知识节点要读它、智能体工具也会写它。领域层抛 FastAPI 的异常,这些非 HTTP 的
调用方就得反过来 catch HTTPException 再翻回自己的领域错误,而那正是此前 `domain/boards/canvas.py`
和 `workflows/executors/knowledge.py` 在做的事。

状态码由边界统一翻(见 main.py 的异常处理器),每个子类各对应一个**故意的**答案。
与 `domain/permissions` 同构。
"""
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.domain import sharing
from app.domain.sharing import AGENT_SESSION_KIND as SESSION_SHARE_KIND
from app.domain.authority import Actor, actor_id, ensure
from app.domain.note_types import NoteContent, NoteRevisionOrigin
from app.db.models import Asset, AgentMessage, AgentSession, Board, Note, NoteRevision, Project
from app.db.model_base import now


class NoteDomainError(LocalizedError, ValueError):
    """笔记领域说不行。带文案 key(`noteErr_*`);`status` 由子类给,边界照着翻(见 main.py)。"""

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
        raise NoteNotFound("noteErr_notFound")
    return note


def snapshot(note: Note) -> dict:
    return {key: getattr(note, key) for key in FIELDS}


def validate_content(db: Session, workspace_id: str, content: NoteContent, *, actor: Actor,
                     existing_sources: list[dict] | None = None) -> dict:
    """落库前的一份笔记内容。`actor` 是**替谁写**:引用一条对话消息,得是这个人看得见的那次对话。

    笔记是工作区的,对话却是某人的私人线程(domain/sharing.KINDS)。只查「消息在这个工作区」的话,同事猜到
    别人私有对话里的消息 id 就能写进来 —— 读不到内容,却能借「写不写得进」探出这个 id 在不在,写进去的引用
    还会以「来源」挂着。判据和读回来的那一刻(routes/notes.source_message → readable_session)是同一份
    `may_use`,于是写得进的引用一定读得回来;看不见和不存在给同一个错误。

    `actor` 没有缺省:没有「不知道是谁就放行」这一档。说不出是谁(None)时引用不了任何对话消息,
    和 `sharing.may_use` 同一条。工作流传的是整份 `Authority`:被执行那一版图的担保人也得看得见。
    """
    data = content.model_dump()
    data["title"] = data["title"].strip()
    for key in ("tags", "topics"):
        data[key] = list(dict.fromkeys(s.strip() for s in data[key] if s.strip()))
        if any(len(s) > 80 for s in data[key]):
            raise NoteDomainError("noteErr_tagTooLong")
    if data["project_id"]:
        project = db.get(Project, data["project_id"])
        if project is None or project.workspace_id != workspace_id:
            raise NoteNotFound("noteErr_projectNotFound")
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
            raise NoteNotFound("noteErr_sourceNotInWorkspace")
        if kind == "message":
            _ensure_cites_session(db, obj, actor)
        if kind == "note":
            if obj.trashed:
                raise NoteConflict("noteErr_referencedTrashed")
            source["revision"] = source["revision"] or obj.revision
            if db.get(NoteRevision, (key, source["revision"])) is None:
                raise NoteNotFound("noteErr_versionNotFound")
    return data


def _ensure_cites_session(db: Session, session: AgentSession, actor: Actor) -> None:
    """引用这次对话里的消息之前:`actor` 得看得见它。

    跑的人看不见、或者被执行那一版图没有担保人看得见,都和「消息不存在」同一个答案 —— 分开答就是告诉他
    「这里有一条你看不到的消息」。
    """
    def hidden(*_: object) -> NoteNotFound:
        return NoteNotFound("noteErr_sourceNotInWorkspace")

    ensure(actor, lambda user: sharing.may_use(db, SESSION_SHARE_KIND, session, user), denied=hidden, unvouched=hidden)


def _record_revision(db: Session, note_id: str, revision: int, data: dict, *, actor: Actor,
                     origin: NoteRevisionOrigin, restored_from: int | None = None) -> None:
    db.add(NoteRevision(note_id=note_id, revision=revision, snapshot=data, origin=origin,
                        created_by=actor_id(actor), restored_from=restored_from))


def create_note(db: Session, workspace_id: str, content: NoteContent, *, actor: Actor,
                origin: NoteRevisionOrigin) -> Note:
    """`origin` 没有缺省:每个写笔记的地方都得说出这一版是怎么来的(版本记录里给人看)。"""
    note = Note(workspace_id=workspace_id, **validate_content(db, workspace_id, content, actor=actor))
    db.add(note)
    db.flush()
    _record_revision(db, note.id, note.revision, snapshot(note), actor=actor, origin=origin)
    db.flush()
    db.refresh(note)
    return note


def save_note(db: Session, workspace_id: str, note_id: str, base_revision: int, content: NoteContent, *,
              actor: Actor, origin: NoteRevisionOrigin, restored_from: int | None = None,
              restored_sources: list[dict] | None = None) -> Note:
    """写成新的一版。笔记上已有的来源(和要恢复的那一版上的)原样放行,不再按 `actor` 重判:它们落库时
    已经过了当时写的那个人的闸,同事改正文不该因为看不见别人引的那条消息而写不进;新加的来源照判。"""
    note = get_note(db, workspace_id, note_id)
    if note.revision != base_revision:
        raise NoteConflict("noteErr_changedElsewhere")
    data = validate_content(db, workspace_id, content, actor=actor,
                            existing_sources=note.sources + (restored_sources or []))
    if data == snapshot(note):
        return note
    # Compare-and-swap also catches two requests that read the same revision concurrently.
    result = db.execute(update(Note).where(Note.id == note_id, Note.revision == base_revision).values(
        **data, revision=base_revision + 1, updated_at=now(),
    ), execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        # 条件 UPDATE 一行没动,不用回滚(那会把调用方这次用例里别的改动一起丢掉);
        # 让内存里这份过期,重试(append_note)时读到的是库里最新的一版。
        db.expire(note)
        raise NoteConflict("noteErr_changedElsewhere")
    _record_revision(db, note_id, base_revision + 1, data, actor=actor, origin=origin, restored_from=restored_from)
    db.flush()
    db.refresh(note)
    return note


def purge_note(db: Session, workspace_id: str, note_id: str, base_revision: int) -> None:
    """永久删除。只删回收站里的,而且修订号得对得上 —— 条件删除:看到的那一版之后有人恢复或改过它,
    就不删(409),而不是把别人刚救回来的那篇一并抹掉。"""
    note = get_note(db, workspace_id, note_id)
    if not note.trashed:
        raise NoteConflict("noteErr_trashFirst")
    result = db.execute(delete(Note).where(
        Note.id == note_id, Note.workspace_id == workspace_id, Note.trashed.is_(True), Note.revision == base_revision,
    ))
    if result.rowcount != 1:
        raise NoteConflict("noteErr_changedBeforeDelete")


#: 追加撞上并发写入时重读当前修订再试几次。冲突只可能来自"另一次写入刚落地",
#: 重读就能解决;给上限只是不在病态争用下无限打转。
#: 追加的内容与原文之间用它隔开。**前端按同一个串认出"这次改动是纯追加"**,从而把
#: 后台追加并进正在编辑的草稿而不打断打字 —— 见 contracts/shared-constants.json。
APPEND_SEPARATOR = "\n\n"

APPEND_RETRIES = 4


def append_note(db: Session, workspace_id: str, note_id: str, markdown: str,
                sources: list[dict], *, actor: Actor, origin: NoteRevisionOrigin) -> Note:
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
            raise NoteConflict("noteErr_restoreFirst")
        data = snapshot(note)
        data["markdown"] = APPEND_SEPARATOR.join(filter(None, [note.markdown, markdown]))
        data["sources"] = note.sources + sources
        try:
            return save_note(db, workspace_id, note_id, note.revision,
                             NoteContent.model_validate(data), actor=actor, origin=origin)
        except NoteConflict:
            # 只可能是修订号对不上:读到写之间有人抢先落地了一版,重读再追加就好。
            # 「在回收站里」同样是 NoteConflict,但它在 try 之外就抛掉了 —— 那种重试
            # 一万次也还在回收站。
            if attempt == APPEND_RETRIES - 1:
                raise
    raise AssertionError("unreachable")  # pragma: no cover


def query_notes(db: Session, workspace_id: str, query: str = "", *, limit: int = 20, offset: int = 0, trashed: bool = False,
                favorite: bool = False, topic: str = "") -> list[Note]:
    """Literal, workspace-scoped knowledge lookup; excludes the recycle bin.

    「只看收藏」「某个主题」**在这里筛**,和分页同一层。此前笔记页把前 200 条拉回来再在浏览器里筛:
    收藏排在 200 条之后时,空态写着「还没有收藏」,底下却挂着「加载更多」。
    """
    import json
    from sqlalchemy import or_, cast, String, func
    stmt = select(Note).where(Note.workspace_id == workspace_id, Note.trashed == trashed)
    if favorite:
        stmt = stmt.where(Note.favorite.is_(True))
    if topic:
        #: 主题是 JSON 数组里的一项:按元素**整项相等**比,不按子串 ——「研究」不该筛出「研究生」。
        each = func.json_each(Note.topics).table_valued("value")
        stmt = stmt.where(select(each.c.value).where(each.c.value == topic).exists())
    for term in query.strip().split():
        escaped = json.dumps(term, ensure_ascii=True)[1:-1]
        stmt = stmt.where(or_(Note.title.icontains(term, autoescape=True), Note.markdown.icontains(term, autoescape=True),
                              *(cast(column, String).icontains(value, autoescape=True)
                                for column in (Note.tags, Note.topics) for value in (term, escaped))))
    return list(db.scalars(stmt.order_by(Note.updated_at.desc(), Note.id).offset(offset).limit(limit)))


def note_topics(db: Session, workspace_id: str, *, trashed: bool = False) -> list[str]:
    """这个工作区(回收站内 / 外)用到过的主题,最近改过的笔记里的排在前面 —— 笔记页的主题下拉用它。

    和筛选一样不能从已加载的那一页里凑:没翻到的笔记里的主题会选不到。只取主题这一列。
    """
    rows = db.scalars(
        select(Note.topics)
        .where(Note.workspace_id == workspace_id, Note.trashed == trashed)
        .order_by(Note.updated_at.desc(), Note.id)
    )
    return list(dict.fromkeys(topic for topics in rows for topic in (topics or []) if topic))


def read_reference(db: Session, workspace_id: str, note_id: str, revision: int | None = None) -> dict:
    """Resolve a source only after checking workspace and recycle-bin state."""
    from urllib.parse import quote
    note = get_note(db, workspace_id, note_id)
    if note.trashed:
        raise NoteConflict("noteErr_referencedTrashedRestore")
    version = note.revision if revision is None else revision
    row = db.get(NoteRevision, (note.id, version))
    if row is None:
        raise NoteNotFound("noteErr_versionNotFound")
    return {"note_id": note.id, "revision": version, "title": row.snapshot["title"],
            "markdown": row.snapshot["markdown"], "tags": row.snapshot["tags"],
            "citation_url": f"#/notes?note={quote(note.id)}&revision={version}"}
