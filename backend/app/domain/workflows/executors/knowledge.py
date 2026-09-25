"""Knowledge nodes share the note domain and never read across workspaces."""
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.domain.note_types import NoteContent
from app.domain.notes import NoteDomainError, create_note, query_notes, read_reference
from app.domain.workflows import WorkflowDomainError, field_name
from app.domain.workflows.executors import RunScope, register


#: 搜索结果每条摘录多长,以及命中处前面留多少上下文。
_EXCERPT_CHARS = 1000
_EXCERPT_LEAD = 160


def _integer(value, default, minimum, maximum, key):
    if value in (None, ""):
        return default
    try:
        number = int(value)
        if isinstance(value, bool) or float(value) != number or not minimum <= number <= maximum:
            raise ValueError()
        return number
    except (ValueError, TypeError, OverflowError) as exc:
        raise WorkflowDomainError(
            "wfErr_integerRange", params={"field": field_name(key), "min": minimum, "max": maximum}
        ) from exc


@register("note_search")
def note_search(db: Session, scope: RunScope, config: dict) -> dict:
    query = str(config.get("query") or "").strip()
    if len(query) > 300:
        raise WorkflowDomainError("wfErr_queryTooLong")
    limit = _integer(config.get("limit"), 10, 1, 50, "limit")
    offset = _integer(config.get("offset"), 0, 0, 1000000, "offset")
    rows = query_notes(db, scope.workspace_id, query, limit=limit + 1, offset=offset)
    matches = []
    for note in rows[:limit]:
        ref = read_reference(db, scope.workspace_id, note.id)
        # An excerpt is deliberately labelled: read_note supplies the full source.
        markdown = ref.pop("markdown")
        at = max(0, markdown.casefold().find(query.split()[0].casefold()) - _EXCERPT_LEAD) if query else 0
        # 窗口往命中处挪,但**不越过全文末尾一窗的位置**:放得下的笔记从头给全文,不切开头。
        at = min(at, max(0, len(markdown) - _EXCERPT_CHARS))
        excerpt = markdown[at:at + _EXCERPT_CHARS]
        # 切了就说切了 —— 开头切掉和结尾切掉一样,下游据此决定要不要 note_read。
        matches.append({**ref, "excerpt": excerpt, "truncated": len(excerpt) < len(markdown)})
    return {"notes": matches, "ids": [r["note_id"] for r in matches], "count": len(matches),
            "has_more": len(rows) > limit,
            "text": "\n\n".join(f"[{r['title'] or '未命名笔记'}]({r['citation_url']})\n{r['excerpt']}" for r in matches)}


@register("note_read")
def note_read(db: Session, scope: RunScope, config: dict) -> dict:
    revision = _integer(config.get("revision"), None, 1, 1000000000, "revision")
    try:
        ref = read_reference(db, scope.workspace_id, str(config.get("note_id") or ""), revision)
    except NoteDomainError as exc:
        # 领域到领域的翻译:笔记读不到,对工作流来说是这个节点失败。
        raise WorkflowDomainError.from_error(exc) from exc
    return {**ref, "text": ref["markdown"]}


@register("note_create")
def note_create(db: Session, scope: RunScope, config: dict) -> dict:
    try:
        tags = config.get("tags") or ""
        tags = tags if isinstance(tags, list) else str(tags).replace("，", ",").split(",")
        content = NoteContent(title=config.get("title") or "", markdown=config.get("markdown") or "", tags=tags)
        if not content.markdown.strip():
            raise WorkflowDomainError("wfErr_noteBodyEmpty")
        note = create_note(db, scope.workspace_id, content)
        ref = read_reference(db, scope.workspace_id, note.id)
        return {"note_id": ref["note_id"], "title": ref["title"], "revision": ref["revision"], "citation_url": ref["citation_url"]}
    except (NoteDomainError, ValidationError) as exc:
        raise WorkflowDomainError.from_error(exc) from exc
