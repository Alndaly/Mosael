"""Knowledge nodes share the note domain and never read across workspaces."""
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db.models import Workflow
from app.domain.note_types import NoteContent
from app.domain.notes import create_note, query_notes, read_reference
from app.domain.workflows import WorkflowDomainError
from app.domain.workflows.executors import register


def _integer(value, default, minimum, maximum, label):
    if value in (None, ""):
        return default
    try:
        number = int(value)
        if isinstance(value, bool) or float(value) != number or not minimum <= number <= maximum:
            raise ValueError()
        return number
    except (ValueError, TypeError, OverflowError) as exc:
        raise WorkflowDomainError(f"{label}必须是 {minimum} 到 {maximum} 的整数") from exc


@register("note_search")
def note_search(db: Session, workflow: Workflow, config: dict) -> dict:
    query = str(config.get("query") or "").strip()
    if len(query) > 300:
        raise WorkflowDomainError("检索词不能超过 300 字")
    limit = _integer(config.get("limit"), 10, 1, 50, "返回条数")
    offset = _integer(config.get("offset"), 0, 0, 1000000, "起始位置")
    rows = query_notes(db, workflow.workspace_id, query, limit=limit + 1, offset=offset)
    matches = []
    for note in rows[:limit]:
        ref = read_reference(db, workflow.workspace_id, note.id)
        # An excerpt is deliberately labelled: read_note supplies the full source.
        markdown = ref.pop("markdown")
        at = max(0, markdown.casefold().find(query.split()[0].casefold()) - 160) if query else 0
        matches.append({**ref, "excerpt": markdown[at:at + 1000], "truncated": len(markdown) > 1000})
    return {"notes": matches, "ids": [r["note_id"] for r in matches], "count": len(matches),
            "has_more": len(rows) > limit,
            "text": "\n\n".join(f"[{r['title'] or '未命名笔记'}]({r['citation_url']})\n{r['excerpt']}" for r in matches)}


@register("note_read")
def note_read(db: Session, workflow: Workflow, config: dict) -> dict:
    revision = _integer(config.get("revision"), None, 1, 1000000000, "版本")
    try:
        ref = read_reference(db, workflow.workspace_id, str(config.get("note_id") or ""), revision)
    except HTTPException as exc:
        raise WorkflowDomainError(str(exc.detail)) from exc
    return {**ref, "text": ref["markdown"]}


@register("note_create")
def note_create(db: Session, workflow: Workflow, config: dict) -> dict:
    try:
        tags = config.get("tags") or ""
        tags = tags if isinstance(tags, list) else str(tags).replace("，", ",").split(",")
        content = NoteContent(title=config.get("title") or "", markdown=config.get("markdown") or "", tags=tags)
        if not content.markdown.strip():
            raise WorkflowDomainError("笔记正文不能为空")
        note = create_note(db, workflow.workspace_id, content)
        ref = read_reference(db, workflow.workspace_id, note.id)
        return {"note_id": ref["note_id"], "title": ref["title"], "revision": ref["revision"], "citation_url": ref["citation_url"]}
    except (HTTPException, ValidationError) as exc:
        raise WorkflowDomainError(str(exc.detail) if isinstance(exc, HTTPException) else str(exc)) from exc
