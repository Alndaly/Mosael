"""系统剪贴板读写:整机副作用,只给部署管理员,并且每次都问。"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain import host_files
from app.domain.agent.computer_use import ComputerUseError, clipboard_read, clipboard_write
from app.domain.agent.confirmable.registry import CardRequest, ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError


def _guard(db: Session, actor: str | None) -> None:
    try:
        host_files.ensure_whole_machine(db, actor=actor)
    except host_files.HostFileNotAllowed as exc:
        raise ConfirmationError(exc.key, **exc.params) from exc


def _validate_read(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    return None


def _summarize_read(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_computerClipboardRead", {}


def _execute_read(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    _guard(db, actor)
    try:
        return clipboard_read()
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


def _validate_write(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    text = payload.get("text")
    if not isinstance(text, str) or len(text) > 100_000:
        raise ConfirmationError("confirmErr_computerClipboardText")


def _summarize_write(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_computerClipboardWrite", {"chars": len(str(payload.get("text") or ""))}


def _execute_write(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    _guard(db, actor)
    try:
        return clipboard_write(confirmation.payload.get("text", ""))
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


class ComputerClipboardReadRequest(CardRequest):
    """`computer_clipboard_read` 这张卡收的参数(和工具那侧拼的一致,见 tests/test_card_requests)。"""

    pass


confirmable_tool(ConfirmableTool(
    name="computer_clipboard_read",
    request=ComputerClipboardReadRequest,
    permission="external",
    cost="none",
    writes=(),
    always_asks=True,
    validate=_validate_read,
    summarize=_summarize_read,
    execute=_execute_read,
))


class ComputerClipboardWriteRequest(CardRequest):
    """`computer_clipboard_write` 这张卡收的参数(和工具那侧拼的一致,见 tests/test_card_requests)。"""

    text: str


confirmable_tool(ConfirmableTool(
    name="computer_clipboard_write",
    request=ComputerClipboardWriteRequest,
    permission="external",
    cost="none",
    writes=(),
    always_asks=True,
    validate=_validate_write,
    summarize=_summarize_write,
    execute=_execute_write,
))
