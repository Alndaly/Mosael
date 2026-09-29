"""外部来源的会话(飞书……)挂进**同一条** turn 管线的两个口子。

此前飞书在自己的子进程里另写了一遍 turn:自己拼系统提示、自己解析供应商、自己调 run_turn、
自己落库 —— 和 host 那一份各走各的。于是桌面端有的(排队、失败轮留轨迹、计费、上下文补全、
失败也回存记忆)飞书一样都没有,改一处漏一处。

现在外部来源只做两件 host 不知道的事:

- ``system_note(db, session)``:这类会话额外的系统提示(比如飞书的权限档、回复要短)。
- ``turn_finished(session_id)``:一轮跑完(成功或失败)之后把结果送回原渠道。

登记在这里而不是让 host 去 import 集成层 —— 领域不依赖集成(见 tests/test_import_layering)。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import AgentSession

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExternalOrigin:
    system_note: Callable[[Session, AgentSession], str] | None = None
    turn_finished: Callable[[str], None] | None = None


_origins: dict[str, ExternalOrigin] = {}


def register(origin: str, handler: ExternalOrigin) -> None:
    _origins[origin] = handler


def system_note(db: Session, session: AgentSession) -> str:
    handler = _origins.get(session.origin or "")
    if handler is None or handler.system_note is None:
        return ""
    return handler.system_note(db, session)


def turn_finished(origin: str | None, session_id: str) -> None:
    """一轮收尾后调用。回送失败只记日志 —— 渠道那头出问题不该连累会话本身。"""
    handler = _origins.get(origin or "")
    if handler is None or handler.turn_finished is None:
        return
    try:
        handler.turn_finished(session_id)
    except Exception:  # noqa: BLE001 —— 见 docstring
        logger.exception("delivering a finished turn to %s failed session=%s", origin, session_id)
