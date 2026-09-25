"""画板上存着的**被取代的插件工具格**,改写成取代它的那个工具。

工具格(ADR 0021 P2)存的是 `form.producer = "node:plugin.<包>.<工具>"`、`form.config`(填的值)和
`form.bindings`(字段 → 从哪几格来)。插件报出的新工具声明了 `replaces` 时(见
domain/workflows/plugin_references,规则在那边一处),这里用同一套判据改画板:配置按那张表改名,
绑定的字段名跟着改;有一格对不上就不动这一格。画板的数据归画板域写(见 domain/ownership),
所以它住在这里而不是工作流那边。
"""

from __future__ import annotations

import logging
from copy import deepcopy
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Board, PluginInstance
from app.domain.boards.producer_ids import node_producer_id, node_type_of

logger = logging.getLogger(__name__)


def _rewrite_item(item: dict[str, Any], found: list[Any]) -> dict[str, Any] | None:
    from app.domain.workflows.plugin_references import MISSING, rewrite_node

    form = item.get("form") if isinstance(item.get("form"), dict) else None
    node_type = node_type_of(str((form or {}).get("producer") or ""))
    if form is None or not node_type:
        return None
    result = rewrite_node(node_type, dict(form.get("config") or {}), found)
    if result is None:
        return None
    new_type, converted, replacement = result
    bindings = form.get("bindings") if isinstance(form.get("bindings"), dict) else {}
    renamed: dict[str, Any] = {}
    for field, refs in bindings.items():
        target = replacement.target(str(field))
        if target is MISSING:
            return None
        renamed[target] = refs
    return {**item, "form": {**form, "producer": node_producer_id(new_type), "config": converted, "bindings": renamed}}


def rewrite_replaced_tools(db: Session) -> int:
    """把库里所有画板上能改的老插件工具格改掉。返回改了几块画板。"""
    from app.domain.workflows.plugin_references import replacements

    found = replacements(db)
    if not found:
        return 0
    changed = 0
    for board in db.scalars(select(Board)):
        canvas = board.canvas if isinstance(board.canvas, dict) else {}
        items = canvas.get("items") if isinstance(canvas.get("items"), list) else []
        touched = False
        rewritten_items = []
        for item in items:
            rewritten = _rewrite_item(item, found) if isinstance(item, dict) else None
            touched = touched or rewritten is not None
            rewritten_items.append(rewritten if rewritten is not None else item)
        if not touched:
            continue
        board.canvas = {**deepcopy(canvas), "items": rewritten_items}
        board.revision = (board.revision or 0) + 1
        changed += 1
    db.commit()
    if changed:
        logger.info("把 %d 块画板上的老插件工具格改写成了取代它的工具", changed)
    return changed


def _after_refresh(db: Session, instance: PluginInstance) -> None:
    rewrite_replaced_tools(db)


def install() -> None:
    from app.domain.plugins import dynamic_tools

    dynamic_tools.on_refreshed(_after_refresh)


__all__ = ["install", "rewrite_replaced_tools"]
