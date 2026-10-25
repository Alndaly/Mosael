"""Computer Use 的桌面动作(ADR 0081 P2):点、输入、滚动。

只认两种目标:AX 元素令牌,或绑定一次截图的像素坐标。目标是否过期、窗口是否移动、
应用是否受保护由 Electron 驱动复核;这里只校验形状并开确认卡。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.agent.computer_use import (
    CLICK_BUTTONS,
    MAX_TYPE_CHARS,
    ComputerUseError,
)
from app.domain.agent.computer_use import desktop_click as use_click
from app.domain.agent.computer_use import desktop_scroll as use_scroll
from app.domain.agent.computer_use import desktop_type as use_type
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError


def _target(payload: dict[str, Any]) -> dict[str, Any]:
    token = str(payload.get("token") or "").strip()
    capture_id = str(payload.get("capture_id") or "").strip()
    if bool(token) == bool(capture_id):
        raise ConfirmationError("confirmErr_computerDesktopTarget")
    if token:
        return {"token": token}
    x, y = payload.get("x"), payload.get("y")
    for key, value in (("x", x), ("y", y)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 0:
            raise ConfirmationError(f"confirmErr_computerClickCoordinate: {key} must be a non-negative number")
    return {"capture_id": capture_id, "x": int(x), "y": int(y)}


def _scale(payload: dict[str, Any]) -> float:
    if payload.get("token"):
        return 1.0
    value = payload.get("scale", 1)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.25 <= float(value) <= 1:
        raise ConfirmationError("confirmErr_computerClickScale")
    return float(value)


def _summary_keys(action: str, payload: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    if payload.get("token"):
        return f"confirm_computerDesktop{action}Token", {"token": str(payload.get("token"))[:120]}
    return f"confirm_computerDesktop{action}Pixel", {
        "x": int(payload.get("x", 0)),
        "y": int(payload.get("y", 0)),
    }


def _validate_click(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    _target(payload)
    _scale(payload)
    button = str(payload.get("button") or "left").strip().lower()
    if button not in CLICK_BUTTONS:
        raise ConfirmationError("confirmErr_computerClickButton")
    count = payload.get("click_count", 1)
    if isinstance(count, bool) or not isinstance(count, (int, float)) or int(count) not in (1, 2):
        raise ConfirmationError("confirmErr_computerClickCount")


def _summarize_click(db: Session, payload: dict[str, Any]) -> Summary:
    key, params = _summary_keys("Click", payload)
    return key, params


def _execute_click(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    try:
        return use_click(
            token=payload.get("token", ""),
            capture_id=payload.get("capture_id", ""),
            x=payload.get("x"),
            y=payload.get("y"),
            button=str(payload.get("button") or "left"),
            click_count=payload.get("click_count", 1),
            scale=_scale(payload),
        )
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


confirmable_tool(ConfirmableTool(
    name="computer_desktop_click",
    permission="edit",
    cost="none",
    writes=(),
    validate=_validate_click,
    summarize=_summarize_click,
    execute=_execute_click,
))


def _validate_type(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    _target(payload)
    _scale(payload)
    text = payload.get("text")
    if not isinstance(text, str) or not text:
        raise ConfirmationError("confirmErr_computerTypeEmpty")
    if len(text) > MAX_TYPE_CHARS:
        raise ConfirmationError("confirmErr_computerTypeTooLong", chars=MAX_TYPE_CHARS)


def _summarize_type(db: Session, payload: dict[str, Any]) -> Summary:
    key, params = _summary_keys("Type", payload)
    return key, {**params, "text": str(payload.get("text") or "")[:400]}


def _execute_type(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    try:
        return use_type(
            text=payload.get("text", ""),
            token=payload.get("token", ""),
            capture_id=payload.get("capture_id", ""),
            x=payload.get("x"),
            y=payload.get("y"),
            scale=_scale(payload),
        )
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


confirmable_tool(ConfirmableTool(
    name="computer_desktop_type",
    permission="edit",
    cost="none",
    writes=(),
    validate=_validate_type,
    summarize=_summarize_type,
    execute=_execute_type,
))


def _validate_scroll(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    _target(payload)
    _scale(payload)
    dy = payload.get("dy")
    if isinstance(dy, bool) or not isinstance(dy, (int, float)) or int(dy) == 0 or abs(int(dy)) > 30:
        raise ConfirmationError("confirmErr_computerScrollDy")


def _summarize_scroll(db: Session, payload: dict[str, Any]) -> Summary:
    notches = int(payload.get("dy") or 0)
    direction = "Down" if notches > 0 else "Up"
    suffix = "Token" if payload.get("token") else "Pixel"
    key = f"confirm_computerDesktopScroll{direction}{suffix}"
    if payload.get("token"):
        return key, {"token": str(payload.get("token"))[:120], "steps": abs(notches)}
    return key, {"x": int(payload.get("x", 0)), "y": int(payload.get("y", 0)), "steps": abs(notches)}


def _execute_scroll(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    try:
        return use_scroll(
            dy=payload.get("dy", 0),
            token=payload.get("token", ""),
            capture_id=payload.get("capture_id", ""),
            x=payload.get("x"),
            y=payload.get("y"),
            scale=_scale(payload),
        )
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


confirmable_tool(ConfirmableTool(
    name="computer_desktop_scroll",
    permission="edit",
    cost="none",
    writes=(),
    validate=_validate_scroll,
    summarize=_summarize_scroll,
    execute=_execute_scroll,
))
