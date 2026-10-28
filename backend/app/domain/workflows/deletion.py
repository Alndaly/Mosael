"""删一个工作流,以及依赖它的那些东西跟着怎么办。

绑着它的定时任务、触发器要**在同一个事务里停用** —— 此前删工作流不管它们:任务仍是启用的,到点照样触发、照样失败;
触发器每来一条飞书消息就白试一次、再喊一次主人(ADR 0065 §5)。这两样都依赖工作流,工作流不能反过来认识它们
(见 tests/test_import_layering),所以它们在组装根(app.main)登记到这里;此前这一步写在删除的路由里,
别的入口删工作流就会漏掉。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Workflow

Listener = Callable[[Session, Workflow], Any]
_listeners: list[Listener] = []


def on_deleting(listener: Listener) -> None:
    """登记一项「工作流删掉之前,依赖它的东西怎么办」。和删除在同一个事务里。"""
    if listener not in _listeners:
        _listeners.append(listener)


def delete_workflow(db: Session, workflow: Workflow) -> None:
    """删掉这个工作流。**调用方负责鉴权**;不提交(入口层的事务一起提交)。"""
    for listener in _listeners:
        listener(db, workflow)
    db.delete(workflow)


__all__ = ["delete_workflow", "on_deleting"]
