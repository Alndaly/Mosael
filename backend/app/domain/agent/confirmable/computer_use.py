"""Computer Use 的动手那半边(ADR 0075 的 L1):点一下、输入一段 —— **只碰 Mosael 自己的窗口**。

和截图不同,这两样会真的改变界面状态,所以走确认卡(`permission="edit"`)。但**不声明
「每次都问」**(维护者 2026-10-22):它属于 edit 档,和「改时间线」同一级 —— 本会话始终允许、
auto 档的 edit 直放、bypass 都该对它们生效。所以别的地方(Bypass/auto)已经在问「谁点的头」,
这里不再多拦一道;卡上仍然写清要发生什么(坐标与按钮 / 要输入的字)。

坐标是模型看着的那张(可能缩小过的)图上的像素,缩放换算在 domain/agent/computer_use 里做,
这里只校验形状。
"""

from __future__ import annotations

import base64
import re
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
from app.domain.agent.computer_use import click as use_click
from app.domain.agent.computer_use import drag as use_drag
from app.domain.agent.computer_use import press as use_press
from app.domain.agent.computer_use import screenshot as use_screenshot
from app.domain.agent.computer_use import scroll as use_scroll
from app.domain.agent.computer_use import type_text as use_type
from app.domain.agent.computer_use import wait as use_wait
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError
from app.domain.assets.importer import import_binary_asset
from app.core.i18n import fragment

#: 点的那一下和输入的那一段都只作用在 Mosael 自己的窗口里;后果撤得回(不写库、不出应用)。
#: 但它是**对用户正在看的那一屏**的改动,所以仍然每步确认。


def _coordinate(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or float(value) < 0:
        raise ConfirmationError(f"confirmErr_computerClickCoordinate: {key} must be a non-negative number")
    return int(value)


def _scale(payload: dict[str, Any]) -> float:
    value = payload.get("scale", 1)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.25 <= float(value) <= 1:
        raise ConfirmationError("confirmErr_computerClickScale")
    return float(value)


def _element(payload: dict[str, Any]) -> str:
    token = str(payload.get("token") or "").strip()
    if not token:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9-]{1,64}:\d{1,8}", token):
        raise ConfirmationError("confirmErr_computerElementToken")
    return token


def _validate_click(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    token = _element(payload)
    if not token:
        _coordinate(payload, "x")
        _coordinate(payload, "y")
        _scale(payload)
    button = str(payload.get("button") or "left").strip().lower()
    if button not in CLICK_BUTTONS:
        raise ConfirmationError("confirmErr_computerClickButton")
    count = payload.get("click_count", 1)
    if isinstance(count, bool) or not isinstance(count, (int, float)) or int(count) not in (1, 2):
        raise ConfirmationError("confirmErr_computerClickCount")


def _summarize_click(db: Session, payload: dict[str, Any]) -> Summary:
    token = _element(payload)
    if token:
        name = str(payload.get("name") or token).strip()[:120]
        return "confirm_computerElementClick", {"name": name}
    return "confirm_computerClick", {
        "x": _coordinate(payload, "x"),
        "y": _coordinate(payload, "y"),
        "button": str(payload.get("button") or "left"),
        "count": int(payload.get("click_count", 1)),
    }


def _execute_click(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    try:
        return use_click(
            x=payload.get("x", 0),
            y=payload.get("y", 0),
            button=str(payload.get("button") or "left"),
            click_count=payload.get("click_count", 1),
            scale=float(payload.get("scale", 1)),
            token=payload.get("token", ""),
        )
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


confirmable_tool(ConfirmableTool(
    name="computer_click",
    permission="edit",
    cost="none",
    #: 只动这一屏的界面状态,不写任何数据
    writes=(),
    validate=_validate_click,
    summarize=_summarize_click,
    execute=_execute_click,
))


def _validate_drag(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    for key in ("from_x", "from_y", "to_x", "to_y"):
        _coordinate(payload, key)
    _scale(payload)
    button = str(payload.get("button") or "left").strip().lower()
    if button not in CLICK_BUTTONS:
        raise ConfirmationError("confirmErr_computerClickButton")
    duration = payload.get("duration_ms", DEFAULT_DRAG_MS)
    if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not MIN_DRAG_MS <= int(duration) <= MAX_DRAG_MS:
        raise ConfirmationError("confirmErr_computerDragDuration", min=MIN_DRAG_MS, max=MAX_DRAG_MS)


def _summarize_drag(db: Session, payload: dict[str, Any]) -> Summary:
    return "confirm_computerDrag", {
        "from_x": _coordinate(payload, "from_x"),
        "from_y": _coordinate(payload, "from_y"),
        "to_x": _coordinate(payload, "to_x"),
        "to_y": _coordinate(payload, "to_y"),
        "button": str(payload.get("button") or "left"),
    }


def _execute_drag(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    try:
        return use_drag(
            from_x=payload.get("from_x", 0),
            from_y=payload.get("from_y", 0),
            to_x=payload.get("to_x", 0),
            to_y=payload.get("to_y", 0),
            button=str(payload.get("button") or "left"),
            duration_ms=payload.get("duration_ms", DEFAULT_DRAG_MS),
            scale=float(payload.get("scale", 1)),
        )
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


confirmable_tool(ConfirmableTool(
    name="computer_drag",
    permission="edit",
    cost="none",
    writes=(),
    validate=_validate_drag,
    summarize=_summarize_drag,
    execute=_execute_drag,
))


def _validate_scroll(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    dy = payload.get("dy")
    if isinstance(dy, bool) or not isinstance(dy, (int, float)) or int(dy) == 0 or abs(int(dy)) > 30:
        raise ConfirmationError("confirmErr_computerScrollDy")


def _summarize_scroll(db: Session, payload: dict[str, Any]) -> Summary:
    notches = int(payload.get("dy") or 0)
    if notches > 0:
        return "confirm_computerScrollDown", {"steps": notches}
    return "confirm_computerScrollUp", {"steps": -notches}


def _execute_scroll(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    try:
        return use_scroll(
            dy=payload.get("dy", 0),
            x=payload.get("x"),
            y=payload.get("y"),
            scale=float(payload.get("scale", 1)),
        )
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


confirmable_tool(ConfirmableTool(
    name="computer_scroll",
    permission="edit",
    cost="none",
    writes=(),
    validate=_validate_scroll,
    summarize=_summarize_scroll,
    execute=_execute_scroll,
))


def _input_kind(payload: dict[str, Any]) -> str:
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
    try:
        _input_kind(payload)
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


def _summarize_input(db: Session, payload: dict[str, Any]) -> Summary:
    if str(payload.get("action") or "").strip().lower() == "type":
        return "confirm_computerType", {"text": str(payload.get("text") or "")[:400]}
    key, modifiers = key_payload(payload.get("key"), payload.get("modifiers"))
    pressed = "+".join([*modifiers, key])
    return "confirm_computerKey", {"keys": pressed[:120]}


def _execute_input(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    try:
        if str(payload.get("action") or "").strip().lower() == "type":
            return use_type(text=payload.get("text", ""))
        return use_press(key=payload.get("key"), modifiers=payload.get("modifiers"))
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


def _escalate_input(db: Session, workspace_id: str, payload: dict[str, Any]) -> str | None:
    """带命令修饰键的组合键能退出/提交/删东西,不跟普通输入同档。"""
    if str(payload.get("action") or "").strip().lower() != "press":
        return None
    try:
        _key, modifiers = key_payload(payload.get("key"), payload.get("modifiers"))
    except ComputerUseError:
        return None
    return "external" if any(one in {"cmd", "ctrl", "alt", "meta"} for one in modifiers) else None


confirmable_tool(ConfirmableTool(
    name="computer_input",
    permission="edit",
    cost="none",
    writes=(),
    validate=_validate_input,
    summarize=_summarize_input,
    execute=_execute_input,
    escalate=_escalate_input,
))


BATCH_LIMIT = 8


def _batch_wait(payload: dict[str, Any]) -> tuple[str, int]:
    text = str(payload.get("text") or "").strip()
    if not text or len(text) > 200:
        raise ConfirmationError("confirmErr_computerBatchBadAction", index=0)
    timeout = payload.get("timeout_ms", 5000)
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 100 <= int(timeout) <= 15_000:
        raise ConfirmationError("confirmErr_computerBatchBadAction", index=0)
    return text, int(timeout)


def _batch_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    actions = payload.get("actions")
    if not isinstance(actions, list) or not actions:
        raise ConfirmationError("confirmErr_computerBatchEmpty")
    if len(actions) > BATCH_LIMIT:
        raise ConfirmationError("confirmErr_computerBatchTooMany", limit=BATCH_LIMIT)
    if not all(isinstance(item, dict) for item in actions):
        raise ConfirmationError("confirmErr_computerBatchBadAction", index=1)
    return actions


def _validate_batch(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    actions = _batch_items(payload)
    finish = payload.get("finish_screenshot", True)
    if not isinstance(finish, bool):
        raise ConfirmationError("confirmErr_computerBatchBadAction", index=0)
    for index, item in enumerate(actions, start=1):
        kind = str(item.get("kind") or "").strip().lower()
        try:
            if kind == "click":
                if item.get("token"):
                    raise ConfirmationError("confirmErr_computerBatchToken")
                _validate_click(db, workspace_id, item, actor)
            elif kind == "drag":
                _validate_drag(db, workspace_id, item, actor)
            elif kind == "scroll":
                _validate_scroll(db, workspace_id, item, actor)
            elif kind == "input":
                _validate_input(db, workspace_id, item, actor)
            elif kind == "wait":
                _batch_wait(item)
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
        elif kind == "drag":
            key, params = _summarize_drag(db, item)
        elif kind == "scroll":
            key, params = _summarize_scroll(db, item)
        elif kind == "input":
            key, params = _summarize_input(db, item)
        else:
            text, _timeout = _batch_wait(item)
            key, params = "confirm_computerBatchWait", {"text": text[:120]}
        steps.append(fragment(key, **params))
    return "confirm_computerBatch", {"count": len(steps), "steps": steps}


def _batch_screenshot(db: Session, workspace_id: str) -> str:
    try:
        shot = use_screenshot(scale=0.75)
        asset = import_binary_asset(
            db,
            workspace_id=workspace_id,
            project_id=None,
            data=base64.b64decode(shot["image"]),
            original="computer-batch.png",
            content_type="image/png",
            source="captured",
            name="界面批量操作结果",
        )
        return asset.id
    except Exception:
        return ""


def _execute_batch(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    results: list[dict[str, Any]] = []
    for index, item in enumerate(_batch_items(payload), start=1):
        kind = str(item.get("kind") or "").strip().lower()
        try:
            if kind == "click":
                result = use_click(
                    x=item.get("x", 0), y=item.get("y", 0),
                    button=str(item.get("button") or "left"),
                    click_count=item.get("click_count", 1),
                    scale=float(item.get("scale", 1)),
                )
            elif kind == "drag":
                result = use_drag(
                    from_x=item.get("from_x", 0), from_y=item.get("from_y", 0),
                    to_x=item.get("to_x", 0), to_y=item.get("to_y", 0),
                    button=str(item.get("button") or "left"),
                    duration_ms=item.get("duration_ms", DEFAULT_DRAG_MS),
                    scale=float(item.get("scale", 1)),
                )
            elif kind == "scroll":
                result = use_scroll(
                    dy=item.get("dy", 0), x=item.get("x"), y=item.get("y"),
                    scale=float(item.get("scale", 1)),
                )
            elif kind == "input":
                if str(item.get("action") or "").strip().lower() == "type":
                    result = use_type(text=item.get("text", ""))
                else:
                    result = use_press(key=item.get("key"), modifiers=item.get("modifiers"))
            else:
                text, timeout = _batch_wait(item)
                result = use_wait(text=text, timeout_ms=timeout)
        except ComputerUseError as error:
            shot_id = _batch_screenshot(db, confirmation.workspace_id)
            return {
                "ok": False,
                "failed_index": index,
                "error": str(error),
                "results": results,
                **({"screenshot_asset_id": shot_id} if shot_id else {}),
            }
        results.append({"index": index, "kind": kind, "result": result})
    shot_id = _batch_screenshot(db, confirmation.workspace_id) if payload.get("finish_screenshot", True) else ""
    return {
        "ok": True,
        "results": results,
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
    name="computer_batch",
    permission="edit",
    cost="none",
    writes=(),
    always_asks=True,
    validate=_validate_batch,
    summarize=_summarize_batch,
    execute=_execute_batch,
    escalate=_escalate_batch,
))
