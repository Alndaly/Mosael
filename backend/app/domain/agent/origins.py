"""外部来源的会话(飞书……)挂进**同一条** turn 管线的两个口子。

此前飞书在自己的子进程里另写了一遍 turn:自己拼系统提示、自己解析供应商、自己调 run_turn、
自己落库 —— 和 host 那一份各走各的。于是桌面端有的(排队、失败轮留轨迹、计费、上下文补全、
失败也回存记忆)飞书一样都没有,改一处漏一处。

现在外部来源只做这几件 host 不知道的事:

- ``system_note(db, session)``:这类会话额外的系统提示(比如飞书的权限档、回复要短)。
- ``turn_finished(session_id)``:一轮跑完(成功或失败)之后把结果送回原渠道。
- ``confirmation_opened(db, confirmation)``:这类会话里开出一张确认卡,推到原渠道(飞书把卡片发回那个群)。
  此前推送写在开卡的**路由**里 —— 于是只有经 HTTP 开的卡会推,智能体直接开的卡不会。

登记在这里而不是让 host 去 import 集成层 —— 领域不依赖集成(见 tests/test_import_layering)。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import AgentQuestion, AgentSession, ToolConfirmation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExternalOrigin:
    system_note: Callable[[Session, AgentSession], str] | None = None
    turn_finished: Callable[[str, str | None], None] | None = None
    confirmation_opened: Callable[[Session, ToolConfirmation], str | None] | None = None
    confirmation_settled: Callable[[Session, ToolConfirmation], None] | None = None
    question_opened: Callable[[Session, AgentQuestion], str | None] | None = None
    question_settled: Callable[[Session, AgentQuestion], None] | None = None
    #: 智能体开始 / 结束等用户操作(确认卡、选择卡)。等待时它没有在生成,`Typing` 这类
    #: “正在回复”的状态该摘;等完接着生成时要贴回去。参数是 `(session_id, waiting)`。
    waiting_for_user: Callable[[str, bool], None] | None = None


_origins: dict[str, ExternalOrigin] = {}


def register(origin: str, handler: ExternalOrigin) -> None:
    _origins[origin] = handler


def system_note(db: Session, session: AgentSession) -> str:
    handler = _origins.get(session.origin or "")
    if handler is None or handler.system_note is None:
        return ""
    return handler.system_note(db, session)


def turn_finished(origin: str | None, session_id: str, message_id: str | None = None) -> None:
    """一轮收尾后调用。`message_id` 是这一轮刚落定的 assistant 行 —— 渠道据此发**这一轮**的回复,
    而不是再查“当前最新一条”(下一轮可能已经开始写草稿)。"""
    handler = _origins.get(origin or "")
    if handler is None or handler.turn_finished is None:
        return
    try:
        handler.turn_finished(session_id, message_id)
    except Exception:  # noqa: BLE001 —— 见 docstring
        logger.exception("delivering a finished turn to %s failed session=%s", origin, session_id)


def confirmation_opened(db: Session, confirmation: ToolConfirmation) -> str | None:
    """一张新卡挂在某次外部会话上时,交给那个渠道去推。推送失败只记日志 —— 卡本身已经开好了。
    成功时返回飞书消息 id(只返回卡片 id,不返回降级文字的消息 id)。"""
    if not confirmation.session_id:
        return None
    session = db.get(AgentSession, confirmation.session_id)
    handler = _origins.get((session.origin if session is not None else "") or "")
    if handler is None or handler.confirmation_opened is None:
        return None
    try:
        return handler.confirmation_opened(db, confirmation)
    except Exception:  # noqa: BLE001 —— 见 docstring
        logger.exception("announcing a confirmation to %s failed confirmation=%s", session.origin, confirmation.id)
        return None


def question_opened(db: Session, question: AgentQuestion) -> str | None:
    """一组选项问题挂在外部会话上时,交给那个渠道去推。推送失败只记日志 —— 问题本身已经落库。"""
    session_id = getattr(question, "session_id", None)
    if not session_id:
        return None
    session = db.get(AgentSession, session_id)
    handler = _origins.get((session.origin if session is not None else "") or "")
    if handler is None or handler.question_opened is None:
        return None
    try:
        return handler.question_opened(db, question)
    except Exception:  # noqa: BLE001 —— 渠道那头出问题不该让问题本身消失
        logger.exception("announcing a question to %s failed question=%s", session.origin, getattr(question, "id", ""))
        return None


def confirmation_opened_after_commit(confirmation: ToolConfirmation) -> None:
    """`after_commit` 入口:原会话已经提交,不能再用它发 SQL;新开一个只读会话把卡推出去,
    并把**卡片消息 id** 写回那一行 —— 之后回调超时/应用内批准/过期才有东西可收回。"""
    with SessionLocal() as db:
        message_id = confirmation_opened(db, confirmation)
        if message_id:
            row = db.get(ToolConfirmation, confirmation.id)
            if row is not None:
                row.feishu_message_id = message_id
                db.commit()


def confirmation_settled_after_commit(confirmation: ToolConfirmation) -> None:
    """工具确认卡在应用内/回调里有了结论后,给外部渠道一次收卡的机会。"""
    with SessionLocal() as db:
        session = db.get(AgentSession, confirmation.session_id) if confirmation.session_id else None
        handler = _origins.get((session.origin if session is not None else "") or "")
        if handler is None or handler.confirmation_settled is None:
            return
        try:
            handler.confirmation_settled(db, confirmation)
        except Exception:  # noqa: BLE001 —— 状态已经落库,收卡失败只记日志
            logger.exception("settling confirmation %s on %s failed", confirmation.id, session.origin)


def question_opened_after_commit(question: AgentQuestion) -> None:
    """`after_commit` 入口:同 `confirmation_opened_after_commit`。"""
    with SessionLocal() as db:
        message_id = question_opened(db, question)
        if message_id:
            row = db.get(AgentQuestion, question.id)
            if row is not None:
                row.feishu_message_id = message_id
                db.commit()


def question_settled_after_commit(question: AgentQuestion) -> None:
    """问题在应用内被回答/跳过之后,给外部渠道一次收回原卡的机会。"""
    with SessionLocal() as db:
        session = db.get(AgentSession, question.session_id)
        handler = _origins.get((session.origin if session is not None else "") or "")
        if handler is None or handler.question_settled is None:
            return
        try:
            handler.question_settled(db, question)
        except Exception:  # noqa: BLE001 —— 状态已经落库,收卡失败只记日志
            logger.exception("settling question %s on %s failed", question.id, session.origin)


def waiting_for_user(origin: str | None, session_id: str, waiting: bool) -> None:
    """智能体开始 / 结束等用户操作时通知外部渠道。渠道只做状态展示,失败不影响运行。"""
    handler = _origins.get(origin or "")
    if handler is None or handler.waiting_for_user is None:
        return
    try:
        handler.waiting_for_user(session_id, waiting)
    except Exception:  # noqa: BLE001 —— 状态指示失败不该影响这一轮
        logger.exception("updating %s waiting state failed session=%s waiting=%s", origin, session_id, waiting)
