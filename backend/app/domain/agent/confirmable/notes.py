"""改笔记正文的确认卡工具(edit_note):把一段原文换掉,或在一段原文前后插入。

档位是 edit:笔记的每一版都留着(版本记录里能恢复),笔记页上这一改还会进编辑器的撤销历史 —— 最坏也撤得回。

和 edit_board 同一个做法:开卡时在当前正文上干跑一遍(说不通的在批准之前就拒),批准时落在**那一刻**的
正文上 —— 这中间用户很可能还在别处打字。那段原文已经被改掉了,就失败、什么都不写,不去猜它挪到了哪里。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.i18n import fragment
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError


def _note_in(db: Session, workspace_id: str, payload: dict[str, Any]):
    """这次要改的那篇,**收进这个工作区**,而且不在回收站里。"""
    from app.domain.notes import NoteDomainError, get_note

    try:
        note = get_note(db, workspace_id, str(payload.get("note_id") or ""))
    except NoteDomainError as exc:
        raise ConfirmationError.relay(exc) from exc
    if note.trashed:
        raise ConfirmationError("noteErr_restoreFirst")
    return note


def _edited(markdown: str, payload: dict[str, Any]) -> str:
    from app.domain.notes import NoteDomainError
    from app.domain.notes.passages import apply_passage_edits

    try:
        return apply_passage_edits(markdown, payload.get("operations"))
    except NoteDomainError as exc:
        raise ConfirmationError.relay(exc) from exc


def _validate_edit_note(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    note = _note_in(db, workspace_id, payload)
    _edited(note.markdown, payload)
    #: 卡上那句话要说清改的是哪一篇。下划线开头:参数表里不再列一遍(见前端 confirmationPayload)。
    payload["_title"] = note.title


def _summarize_edit_note(db: Session, payload: dict[str, Any]) -> Summary:
    kinds = [op.get("kind") for op in payload.get("operations") or [] if isinstance(op, dict)]
    changes = [
        fragment(key, count=count)
        for key, count in (("confirm_noteReplaces", kinds.count("replace")), ("confirm_noteInserts", kinds.count("insert")))
        if count
    ]
    title = str(payload.get("_title") or "")
    return "confirm_editNote", {
        "title": title or fragment("confirm_noteUntitled"),
        "changes": changes,
    }


def _execute_edit_note(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    from app.domain.note_types import NoteContent
    from app.domain.notes import NoteDomainError, save_note, snapshot

    payload = confirmation.payload
    note = _note_in(db, confirmation.workspace_id, payload)
    content = snapshot(note)
    content["markdown"] = _edited(note.markdown, payload)
    try:
        saved = save_note(db, confirmation.workspace_id, note.id, note.save_seq,
                          NoteContent.model_validate(content), actor=actor, origin="agent")
    except NoteDomainError as exc:
        raise ConfirmationError.relay(exc) from exc
    return {"note_id": saved.id, "revision": saved.revision}


confirmable_tool(ConfirmableTool(
    name="edit_note",
    permission="edit",
    cost="none",
    summarize=_summarize_edit_note,
    execute=_execute_edit_note,
    validate=_validate_edit_note,
))
