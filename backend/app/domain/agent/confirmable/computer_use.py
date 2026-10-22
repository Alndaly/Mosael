"""Computer Use 的动手那半边(ADR 0075 的 L1):点一下、输入一段 —— **只碰 Mosael 自己的窗口**。

和截图不同,这两样会真的改变界面状态,所以**每一张卡都要人点头**(`always_asks`):不提供
「本会话始终允许」,自动放行与 bypass 也放不过它们。坐标是模型看着的那张(可能缩小过的)图上的
像素,缩放换算在 domain/agent/computer_use 里做,这里只校验形状。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.domain.agent.computer_use import CLICK_BUTTONS, MAX_TYPE_CHARS, ComputerUseError
from app.domain.agent.computer_use import click as use_click
from app.domain.agent.computer_use import type_text as use_type
from app.domain.agent.confirmable.registry import ConfirmableTool, Summary, confirmable_tool
from app.domain.agent.errors import ConfirmationError

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


def _validate_click(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
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
    return "confirm_computerClick", {
        "window": str(payload.get("window") or "main"),
        "x": _coordinate(payload, "x"),
        "y": _coordinate(payload, "y"),
        "button": str(payload.get("button") or "left"),
        "count": int(payload.get("click_count", 1)),
    }


def _execute_click(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    try:
        return use_click(
            window=str(payload.get("window") or "main"),
            x=payload.get("x", 0),
            y=payload.get("y", 0),
            button=str(payload.get("button") or "left"),
            click_count=payload.get("click_count", 1),
            scale=float(payload.get("scale", 1)),
        )
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


def _validate_type(db: Session, workspace_id: str, payload: dict[str, Any], actor: str | None) -> None:
    text = payload.get("text")
    if not isinstance(text, str) or not text:
        raise ConfirmationError("confirmErr_computerTypeEmpty")
    if len(text) > MAX_TYPE_CHARS:
        raise ConfirmationError("confirmErr_computerTypeTooLong", chars=MAX_TYPE_CHARS)


def _summarize_type(db: Session, payload: dict[str, Any]) -> Summary:
    #: 卡上要把**要输入的字**原样给出来 —— 授权界面上看不到内容,等于没让人看清要干什么。
    return "confirm_computerType", {
        "window": str(payload.get("window") or "main"),
        "text": str(payload.get("text") or "")[:400],
    }


def _execute_type(db: Session, confirmation: Any, actor: str | None) -> dict[str, Any]:
    payload = confirmation.payload
    try:
        return use_type(window=str(payload.get("window") or "main"), text=payload.get("text", ""))
    except ComputerUseError as error:
        raise ConfirmationError(str(error)) from None


confirmable_tool(ConfirmableTool(
    name="computer_click",
    permission="edit",
    cost="none",
    #: 只动这一屏的界面状态,不写任何数据
    writes=(),
    #: 每一步都要人点头:不提供「本会话始终允许」,自动放行与 bypass 也放不过(ADR 0075 安全 1)
    always_asks=True,
    validate=_validate_click,
    summarize=_summarize_click,
    execute=_execute_click,
))


confirmable_tool(ConfirmableTool(
    name="computer_type",
    permission="edit",
    cost="none",
    writes=(),
    always_asks=True,
    validate=_validate_type,
    summarize=_summarize_type,
    execute=_execute_type,
))
