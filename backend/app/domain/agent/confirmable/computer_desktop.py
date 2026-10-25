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
from app.domain.agent import replay as replay_store
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError


def _with_replay(confirmation: Any, result: dict[str, Any]) -> dict[str, Any]:
    evidence = result.get("replay")
    if not isinstance(evidence, dict):
        return result
    session_id = getattr(confirmation, "session_id", None)
    if not session_id:
        return {key: value for key, value in result.items() if key != "replay"}
    try:
        return replay_store.store_action_replay(
            session_id=str(session_id),
            replay_id=str(getattr(confirmation, "id", "")),
            replay=evidence,
            result=result,
        )
    except (OSError, ValueError) as error:
        clean = {key: value for key, value in result.items() if key != "replay"}
        clean["replay"] = {"version": 1, "error": str(error)}
        return clean


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


def _point_params(payload: dict[str, Any]) -> dict[str, Any]:
    return {"x": int(payload.get("x", 0)), "y": int(payload.get("y", 0))}


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
    if payload.get("token"):
        return "confirm_computerDesktopClickToken", {"token": str(payload.get("token"))[:120]}
    return "confirm_computerDesktopClickPixel", _point_params(payload)


def _execute_click(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    try:
        return _with_replay(confirmation, use_click(
            token=payload.get("token", ""),
            capture_id=payload.get("capture_id", ""),
            x=payload.get("x"),
            y=payload.get("y"),
            button=str(payload.get("button") or "left"),
            click_count=payload.get("click_count", 1),
            scale=_scale(payload),
        ))
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
    text = str(payload.get("text") or "")[:400]
    if payload.get("token"):
        return "confirm_computerDesktopTypeToken", {"token": str(payload.get("token"))[:120], "text": text}
    return "confirm_computerDesktopTypePixel", {**_point_params(payload), "text": text}


def _execute_type(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    try:
        return _with_replay(confirmation, use_type(
            text=payload.get("text", ""),
            token=payload.get("token", ""),
            capture_id=payload.get("capture_id", ""),
            x=payload.get("x"),
            y=payload.get("y"),
            scale=_scale(payload),
        ))
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
    steps = abs(notches)
    if payload.get("token"):
        token = str(payload.get("token"))[:120]
        if notches > 0:
            return "confirm_computerDesktopScrollDownToken", {"token": token, "steps": steps}
        return "confirm_computerDesktopScrollUpToken", {"token": token, "steps": steps}
    if notches > 0:
        return "confirm_computerDesktopScrollDownPixel", {**_point_params(payload), "steps": steps}
    return "confirm_computerDesktopScrollUpPixel", {**_point_params(payload), "steps": steps}


def _execute_scroll(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    try:
        return _with_replay(confirmation, use_scroll(
            dy=payload.get("dy", 0),
            token=payload.get("token", ""),
            capture_id=payload.get("capture_id", ""),
            x=payload.get("x"),
            y=payload.get("y"),
            scale=_scale(payload),
        ))
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
