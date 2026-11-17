"""Computer Use 的桌面动作(ADR 0081 P2):点、输入、滚动。

只认两种目标:AX 元素令牌,或绑定一次截图的像素坐标。目标是否过期、窗口是否移动、
应用是否受保护由 Electron 驱动复核;这里只校验形状并开确认卡。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.agent.computer_use import (
    CLICK_BUTTONS,
    DEFAULT_DRAG_MS,
    MAX_DRAG_MS,
    MAX_TYPE_CHARS,
    MIN_DRAG_MS,
    ComputerUseError,
    key_payload,
)
from app.domain.agent.computer_use import desktop_click as use_click
from app.domain.agent.computer_use import desktop_drag as use_drag
from app.domain.agent.computer_use import desktop_press as use_press
from app.domain.agent.computer_use import desktop_scroll as use_scroll
from app.domain.agent.computer_use import desktop_type as use_type
from app.domain.agent import replay as replay_store
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError
from app.domain import host_files


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


def _whole_machine_guard(db: Session, actor: str | None) -> None:
    try:
        host_files.ensure_whole_machine(db, actor=actor)
    except host_files.HostFileNotAllowed as exc:
        raise ConfirmationError(exc.key, **exc.params) from exc


def _execute_click(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    _whole_machine_guard(db, actor)
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


#: 跨应用输入不是“改这一屏的视图”，它和 run_host_code 一样是这台电脑上的副作用；auto 档
#: 不能替用户点头。放在 external 档，规则/判断者/人都要过，执行体再要求部署管理员。
confirmable_tool(ConfirmableTool(
    name="computer_desktop_click",
    permission="external",
    cost="none",
    writes=(),
    validate=_validate_click,
    summarize=_summarize_click,
    execute=_execute_click,
))


def _input_action(payload: dict[str, Any]) -> str:
    action = str(payload.get("action") or "").strip().lower()
    if action not in {"type", "press"}:
        raise ConfirmationError("confirmErr_computerInputAction")
    if action == "type":
        text = payload.get("text")
        if not isinstance(text, str) or not text:
            raise ConfirmationError("confirmErr_computerTypeEmpty")
        if len(text) > MAX_TYPE_CHARS:
            raise ConfirmationError("confirmErr_computerTypeTooLong", chars=MAX_TYPE_CHARS)
        if payload.get("key") or payload.get("modifiers"):
            raise ConfirmationError("confirmErr_computerInputMixed")
    else:
        key_payload(payload.get("key"), payload.get("modifiers"))
        if payload.get("text"):
            raise ConfirmationError("confirmErr_computerInputMixed")
    return action


def _validate_input(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    _target(payload)
    _scale(payload)
    click_target = payload.get("click_target", True)
    if not isinstance(click_target, bool):
        raise ConfirmationError("confirmErr_computerInputClickTarget")
    try:
        _input_action(payload)
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


def _summarize_input(db: Session, payload: dict[str, Any]) -> Summary:
    focused = not payload.get("click_target", True)
    if _input_action(payload) == "type":
        text = str(payload.get("text") or "")[:400]
        if payload.get("token"):
            key = "confirm_computerDesktopTypeTokenFocused" if focused else "confirm_computerDesktopTypeToken"
            return key, {"token": str(payload.get("token"))[:120], "text": text}
        key = "confirm_computerDesktopTypePixelFocused" if focused else "confirm_computerDesktopTypePixel"
        return key, {**_point_params(payload), "text": text}
    key, modifiers = key_payload(payload.get("key"), payload.get("modifiers"))
    pressed = "+".join([*modifiers, key])
    if payload.get("token"):
        summary = "confirm_computerDesktopKeyTokenFocused" if focused else "confirm_computerDesktopKeyToken"
        return summary, {"token": str(payload.get("token"))[:120], "keys": pressed}
    summary = "confirm_computerDesktopKeyPixelFocused" if focused else "confirm_computerDesktopKeyPixel"
    return summary, {**_point_params(payload), "keys": pressed}


def _execute_input(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    _whole_machine_guard(db, actor)
    payload = confirmation.payload
    try:
        if _input_action(payload) == "type":
            return _with_replay(confirmation, use_type(
                text=payload.get("text", ""),
                token=payload.get("token", ""),
                capture_id=payload.get("capture_id", ""),
                x=payload.get("x"),
                y=payload.get("y"),
                scale=_scale(payload),
                click_target=payload.get("click_target", True),
            ))
        return _with_replay(confirmation, use_press(
            key=payload.get("key"),
            modifiers=payload.get("modifiers"),
            token=payload.get("token", ""),
            capture_id=payload.get("capture_id", ""),
            x=payload.get("x"),
            y=payload.get("y"),
            scale=_scale(payload),
            click_target=payload.get("click_target", True),
        ))
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


confirmable_tool(ConfirmableTool(
    name="computer_desktop_input",
    permission="external",
    cost="none",
    writes=(),
    validate=_validate_input,
    summarize=_summarize_input,
    execute=_execute_input,
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
    _whole_machine_guard(db, actor)
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
    permission="external",
    cost="none",
    writes=(),
    validate=_validate_scroll,
    summarize=_summarize_scroll,
    execute=_execute_scroll,
))


def _validate_drag(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    capture_id = str(payload.get("capture_id") or "").strip()
    if not capture_id:
        raise ConfirmationError("confirmErr_computerDesktopDragTarget")
    for key in ("from_x", "from_y", "to_x", "to_y"):
        value = payload.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 0:
            raise ConfirmationError(f"confirmErr_computerClickCoordinate: {key} must be a non-negative number")
    _scale(payload)
    button = str(payload.get("button") or "left").strip().lower()
    if button not in CLICK_BUTTONS:
        raise ConfirmationError("confirmErr_computerClickButton")
    duration = payload.get("duration_ms", DEFAULT_DRAG_MS)
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not MIN_DRAG_MS <= int(duration) <= MAX_DRAG_MS:
        raise ConfirmationError("confirmErr_computerDragDuration", min=MIN_DRAG_MS, max=MAX_DRAG_MS)


def _summarize_drag(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_computerDesktopDrag", {
        "from_x": int(payload.get("from_x", 0)),
        "from_y": int(payload.get("from_y", 0)),
        "to_x": int(payload.get("to_x", 0)),
        "to_y": int(payload.get("to_y", 0)),
        "button": str(payload.get("button") or "left"),
    }


def _execute_drag(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    _whole_machine_guard(db, actor)
    payload = confirmation.payload
    try:
        return _with_replay(confirmation, use_drag(
            capture_id=payload.get("capture_id", ""),
            from_x=payload.get("from_x", 0),
            from_y=payload.get("from_y", 0),
            to_x=payload.get("to_x", 0),
            to_y=payload.get("to_y", 0),
            button=str(payload.get("button") or "left"),
            duration_ms=payload.get("duration_ms", DEFAULT_DRAG_MS),
            scale=_scale(payload),
        ))
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


confirmable_tool(ConfirmableTool(
    name="computer_desktop_drag",
    permission="external",
    cost="none",
    writes=(),
    validate=_validate_drag,
    summarize=_summarize_drag,
    execute=_execute_drag,
))
