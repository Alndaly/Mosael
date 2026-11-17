"""Computer Use 的桌面动作(ADR 0081 P2):点、输入、滚动。

只认两种目标:AX 元素令牌,或绑定一次截图的像素坐标。目标是否过期、窗口是否移动、
应用是否受保护由 Electron 驱动复核;这里只校验形状并开确认卡。
"""

from __future__ import annotations

import base64
from typing import Any

from sqlalchemy.orm import Session

from app.domain.agent.computer_use import (
    CLICK_BUTTONS,
    DEFAULT_DRAG_MS,
    KEY_MODIFIERS,
    L1_POINTER_ACTIONS,
    MAX_DRAG_MS,
    MAX_HOLD_MS,
    MAX_TYPE_CHARS,
    MIN_DRAG_MS,
    ComputerUseError,
    key_payload,
)
from app.domain.agent.computer_use import desktop_click as use_click
from app.domain.agent.computer_use import desktop_drag as use_drag
from app.domain.agent.computer_use import desktop_full_screenshot as use_full_screenshot
from app.domain.agent.computer_use import desktop_pointer as use_pointer
from app.domain.agent.computer_use import desktop_press as use_press
from app.domain.agent.computer_use import desktop_screenshot as use_screenshot
from app.domain.agent.computer_use import desktop_scroll as use_scroll
from app.domain.agent.computer_use import desktop_type as use_type
from app.domain.agent.computer_use import desktop_wait as use_wait
from app.domain.agent import replay as replay_store
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError
from app.domain.assets.importer import import_binary_asset
from app.domain import host_files
from app.core.i18n import fragment


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
    modifiers = payload.get("modifiers") or []
    if not isinstance(modifiers, (list, tuple)) or any(str(one) not in KEY_MODIFIERS for one in modifiers):
        raise ConfirmationError("confirmErr_computerPointerModifiers")
    count = payload.get("click_count", 1)
    if isinstance(count, bool) or not isinstance(count, (int, float)) or int(count) not in (1, 2, 3):
        raise ConfirmationError("confirmErr_computerClickCount")


def _summarize_click(db: Session, payload: dict[str, Any]) -> Summary:
    button = str(payload.get("button") or "left").strip().lower()
    count = int(payload.get("click_count", 1))
    mods = [str(one) for one in (payload.get("modifiers") or [])]
    if mods or button == "middle" or count == 3:
        keys = "+".join([*mods, {1: "click", 2: "double-click", 3: "triple-click"}[count]])
        if payload.get("token"):
            return "confirm_computerDesktopSpecialClickToken", {
                "token": str(payload.get("token"))[:120], "keys": keys[:120], "button": button,
            }
        return "confirm_computerDesktopSpecialClickPixel", {**_point_params(payload), "keys": keys[:120], "button": button}
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
            modifiers=payload.get("modifiers"),
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
    hold = payload.get("hold_ms", 0)
    if isinstance(hold, bool) or not isinstance(hold, (int, float)) or not 0 <= int(hold) <= MAX_HOLD_MS:
        raise ConfirmationError("confirmErr_computerHoldMs", max=MAX_HOLD_MS)
    try:
        _input_action(payload)
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


def _summarize_input(db: Session, payload: dict[str, Any]) -> Summary:
    focused = not payload.get("click_target", True)
    if _input_action(payload) == "type":
        text = str(payload.get("text") or "")[:400]
        if payload.get("token"):
            if focused:
                return "confirm_computerDesktopTypeTokenFocused", {
                    "token": str(payload.get("token"))[:120], "text": text,
                }
            return "confirm_computerDesktopTypeToken", {
                "token": str(payload.get("token"))[:120], "text": text,
            }
        if focused:
            return "confirm_computerDesktopTypePixelFocused", {**_point_params(payload), "text": text}
        return "confirm_computerDesktopTypePixel", {**_point_params(payload), "text": text}
    key, modifiers = key_payload(payload.get("key"), payload.get("modifiers"))
    pressed = "+".join([*modifiers, key])
    hold = int(payload.get("hold_ms") or 0)
    if hold:
        if payload.get("token"):
            return "confirm_computerDesktopKeyHoldToken", {
                "token": str(payload.get("token"))[:120], "keys": pressed, "ms": hold,
            }
        return "confirm_computerDesktopKeyHoldPixel", {**_point_params(payload), "keys": pressed, "ms": hold}
    if payload.get("token"):
        if focused:
            return "confirm_computerDesktopKeyTokenFocused", {
                "token": str(payload.get("token"))[:120], "keys": pressed,
            }
        return "confirm_computerDesktopKeyToken", {
            "token": str(payload.get("token"))[:120], "keys": pressed,
        }
    if focused:
        return "confirm_computerDesktopKeyPixelFocused", {**_point_params(payload), "keys": pressed}
    return "confirm_computerDesktopKeyPixel", {**_point_params(payload), "keys": pressed}


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
            hold_ms=payload.get("hold_ms", 0),
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
    dy = payload.get("dy", 0)
    dx = payload.get("dx", 0)
    for value, key in ((dy, "confirmErr_computerScrollDy"), (dx, "confirmErr_computerScrollDx")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(int(value)) > 30:
            raise ConfirmationError(key)
    if int(dy) == 0 and int(dx) == 0:
        raise ConfirmationError("confirmErr_computerScrollDy")


def _summarize_scroll(db: Session, payload: dict[str, Any]) -> Summary:
    dy = int(payload.get("dy") or 0)
    dx = int(payload.get("dx") or 0)
    if dy and dx:
        return "confirm_computerScrollBoth", {"dx": dx, "dy": dy}
    if dx > 0:
        return "confirm_computerScrollRight", {"steps": dx}
    if dx < 0:
        return "confirm_computerScrollLeft", {"steps": -dx}
    steps = abs(dy)
    if payload.get("token"):
        token = str(payload.get("token"))[:120]
        if dy > 0:
            return "confirm_computerDesktopScrollDownToken", {"token": token, "steps": steps}
        return "confirm_computerDesktopScrollUpToken", {"token": token, "steps": steps}
    if dy > 0:
        return "confirm_computerDesktopScrollDownPixel", {**_point_params(payload), "steps": steps}
    return "confirm_computerDesktopScrollUpPixel", {**_point_params(payload), "steps": steps}


def _execute_scroll(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    _whole_machine_guard(db, actor)
    payload = confirmation.payload
    try:
        return _with_replay(confirmation, use_scroll(
            dy=payload.get("dy", 0),
            dx=payload.get("dx", 0),
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


def _validate_pointer(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    _target(payload)
    _scale(payload)
    action = str(payload.get("action") or "").strip().lower()
    if action not in L1_POINTER_ACTIONS:
        raise ConfirmationError("confirmErr_computerPointerAction")
    button = str(payload.get("button") or "left").strip().lower()
    if button not in CLICK_BUTTONS:
        raise ConfirmationError("confirmErr_computerClickButton")
    modifiers = payload.get("modifiers") or []
    if not isinstance(modifiers, (list, tuple)) or any(str(one) not in KEY_MODIFIERS for one in modifiers):
        raise ConfirmationError("confirmErr_computerPointerModifiers")


def _summarize_pointer(db: Session, payload: dict[str, Any]) -> Summary:
    params = {
        "action": str(payload.get("action") or "").strip().lower(),
        "button": str(payload.get("button") or "left"),
    }
    if payload.get("token"):
        return "confirm_computerDesktopPointerToken", {**params, "token": str(payload.get("token"))[:120]}
    return "confirm_computerDesktopPointerPixel", {**_point_params(payload), **params}


def _execute_pointer(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    _whole_machine_guard(db, actor)
    payload = confirmation.payload
    try:
        return _with_replay(confirmation, use_pointer(
            action=payload.get("action"),
            token=payload.get("token", ""),
            capture_id=payload.get("capture_id", ""),
            x=payload.get("x"),
            y=payload.get("y"),
            button=payload.get("button", "left"),
            modifiers=payload.get("modifiers"),
            scale=_scale(payload),
        ))
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


confirmable_tool(ConfirmableTool(
    name="computer_desktop_pointer",
    permission="external",
    cost="none",
    writes=(),
    validate=_validate_pointer,
    summarize=_summarize_pointer,
    execute=_execute_pointer,
))


BATCH_LIMIT = 8


def _batch_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ConfirmationError("confirmErr_computerBatchEmpty")
    if len(actions) > BATCH_LIMIT:
        raise ConfirmationError("confirmErr_computerBatchTooMany", limit=BATCH_LIMIT)
    if not all(isinstance(item, dict) for item in actions):
        raise ConfirmationError("confirmErr_computerBatchBadAction", index=1)
    return actions


def _wait_check(item: dict[str, Any], index: int) -> tuple[int, str, int]:
    pid = item.get("pid")
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ConfirmationError("confirmErr_computerBatchBadAction", index=index)
    text = str(item.get("text") or "").strip()
    if not text or len(text) > 200:
        raise ConfirmationError("confirmErr_computerBatchBadAction", index=index)
    timeout = item.get("timeout_ms", 5000)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 100 <= int(timeout) <= 15_000:
        raise ConfirmationError("confirmErr_computerBatchBadAction", index=index)
    return pid, text, int(timeout)


def _validate_batch(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    actions = _batch_items(payload)
    window_id = payload.get("window_id")
    if window_id not in (None, "") and (isinstance(window_id, bool) or not isinstance(window_id, int) or window_id <= 0):
        raise ConfirmationError("confirmErr_computerBatchBadAction", index=0)
    finish = payload.get("finish_screenshot", True)
    if not isinstance(finish, bool):
        raise ConfirmationError("confirmErr_computerBatchBadAction", index=0)
    for index, item in enumerate(actions, start=1):
        kind = str(item.get("kind") or "").strip().lower()
        try:
            if kind == "click":
                _validate_click(db, workspace_id, item, actor)
            elif kind == "pointer":
                _validate_pointer(db, workspace_id, item, actor)
            elif kind == "scroll":
                _validate_scroll(db, workspace_id, item, actor)
            elif kind == "input":
                _validate_input(db, workspace_id, item, actor)
            elif kind == "drag":
                _validate_drag(db, workspace_id, item, actor)
            elif kind == "wait":
                _wait_check(item, index)
            else:
                raise ConfirmationError("confirmErr_computerBatchBadAction", index=index)
        except ConfirmationError as exc:
            if exc.key == "confirmErr_computerBatchBadAction":
                raise
            raise ConfirmationError("confirmErr_computerBatchBadAction", index=index) from exc
        except Exception as exc:
            raise ConfirmationError("confirmErr_computerBatchBadAction", index=index) from exc


def _summarize_batch(db: Session, payload: dict[str, Any]) -> Summary:
    steps: list[Any] = []
    for item in _batch_items(payload):
        kind = str(item.get("kind") or "").strip().lower()
        if kind == "click":
            key, params = _summarize_click(db, item)
        elif kind == "pointer":
            key, params = _summarize_pointer(db, item)
        elif kind == "scroll":
            key, params = _summarize_scroll(db, item)
        elif kind == "input":
            key, params = _summarize_input(db, item)
        elif kind == "drag":
            key, params = _summarize_drag(db, item)
        else:
            _pid, text, _timeout = _wait_check(item, 1)
            key, params = "confirm_computerBatchWait", {"text": text[:120]}
        steps.append(fragment(key, **params))
    return "confirm_computerBatch", {"count": len(steps), "steps": steps}


def _batch_window_from_results(results: list[dict[str, Any]]) -> int | None:
    """最后一步真正落在哪个窗口;动作结果里有 windowNumber 就用它。"""
    for item in reversed(results):
        result = item.get("result")
        if isinstance(result, dict):
            window = result.get("windowNumber")
            if isinstance(window, int) and not isinstance(window, bool) and window > 0:
                return window
    return None


def _batch_screenshot(db: Session, workspace_id: str, window_id: object) -> str:
    """优先拍最后动作的窗口;没有窗口信息时用全桌面截图兜底。受保护应用在屏则静默跳过。"""
    try:
        if window_id not in (None, ""):
            shot = use_screenshot(window_id=window_id, scale=0.75)
        else:
            shot = use_full_screenshot(scale=0.75)
        asset = import_binary_asset(
            db,
            workspace_id=workspace_id,
            project_id=None,
            data=base64.b64decode(shot["image"]),
            original="desktop-batch.png",
            content_type="image/png",
            source="captured",
            name="桌面批量操作结果",
        )
        return asset.id
    except Exception:
        return ""


def _execute_batch(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    _whole_machine_guard(db, actor)
    payload = confirmation.payload
    results: list[dict[str, Any]] = []
    for index, item in enumerate(_batch_items(payload), start=1):
        kind = str(item.get("kind") or "").strip().lower()
        try:
            if kind == "click":
                result = use_click(
                    token=item.get("token", ""), capture_id=item.get("capture_id", ""),
                    x=item.get("x"), y=item.get("y"), button=item.get("button", "left"),
                    click_count=item.get("click_count", 1), scale=float(item.get("scale", 1)),
                    modifiers=item.get("modifiers"),
                )
            elif kind == "pointer":
                result = use_pointer(
                    action=item.get("action"), token=item.get("token", ""),
                    capture_id=item.get("capture_id", ""), x=item.get("x"), y=item.get("y"),
                    button=item.get("button", "left"), modifiers=item.get("modifiers"),
                    scale=float(item.get("scale", 1)),
                )
            elif kind == "scroll":
                result = use_scroll(
                    dy=item.get("dy", 0), dx=item.get("dx", 0), token=item.get("token", ""),
                    capture_id=item.get("capture_id", ""), x=item.get("x"), y=item.get("y"),
                    scale=float(item.get("scale", 1)),
                )
            elif kind == "input":
                if str(item.get("action") or "").strip().lower() == "type":
                    result = use_type(
                        text=item.get("text", ""), token=item.get("token", ""),
                        capture_id=item.get("capture_id", ""), x=item.get("x"), y=item.get("y"),
                        scale=float(item.get("scale", 1)),
                        click_target=item.get("click_target", True),
                    )
                else:
                    result = use_press(
                        key=item.get("key"), modifiers=item.get("modifiers"),
                        token=item.get("token", ""), capture_id=item.get("capture_id", ""),
                        x=item.get("x"), y=item.get("y"), scale=float(item.get("scale", 1)),
                        click_target=item.get("click_target", True),
                        hold_ms=item.get("hold_ms", 0),
                    )
            elif kind == "drag":
                result = use_drag(
                    capture_id=item.get("capture_id", ""), from_x=item.get("from_x", 0),
                    from_y=item.get("from_y", 0), to_x=item.get("to_x", 0), to_y=item.get("to_y", 0),
                    button=item.get("button", "left"), duration_ms=item.get("duration_ms", DEFAULT_DRAG_MS),
                    scale=float(item.get("scale", 1)),
                )
            else:
                pid, text, timeout = _wait_check(item, index)
                result = use_wait(pid=pid, text=text, timeout_ms=timeout)
        except ComputerUseError as error:
            shot_id = _batch_screenshot(
                db, confirmation.workspace_id,
                payload.get("window_id") or _batch_window_from_results(results),
            )
            return {
                "ok": False, "failed_index": index, "error": str(error), "results": results,
                **({"screenshot_asset_id": shot_id} if shot_id else {}),
            }
        results.append({"index": index, "kind": kind, "result": result})
    shot_id = _batch_screenshot(
        db, confirmation.workspace_id,
        payload.get("window_id") or _batch_window_from_results(results),
    ) if payload.get("finish_screenshot", True) else ""
    return {
        "ok": True, "results": results,
        **({"screenshot_asset_id": shot_id} if shot_id else {}),
    }


def _escalate_batch(db: Session, workspace_id: str, payload: dict[str, Any]) -> str | None:
    for item in payload.get("actions") or []:
        if not isinstance(item, dict) or str(item.get("kind") or "").strip().lower() != "input":
            continue
        if str(item.get("action") or "").strip().lower() != "press":
            continue
        try:
            _key, modifiers = key_payload(item.get("key"), item.get("modifiers"))
        except ComputerUseError:
            continue
        if any(one in {"cmd", "ctrl", "alt", "meta"} for one in modifiers):
            return "external"
    return None


confirmable_tool(ConfirmableTool(
    name="computer_desktop_batch",
    permission="external",
    cost="none",
    writes=(),
    always_asks=True,
    validate=_validate_batch,
    summarize=_summarize_batch,
    execute=_execute_batch,
    escalate=_escalate_batch,
))
