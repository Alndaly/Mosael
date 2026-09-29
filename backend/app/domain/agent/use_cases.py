"""智能体会话周边的用例:会话列表、任务计划、「带我过去」、问用户、跨会话记忆。

闸在这里(见 CONVENTIONS「一次用例一个事务,授权在领域里」):HTTP 路由和智能体工具调同一个函数。
对话的读写闸在 agent/sessions(共享来的对话只能看);记忆按工作区的 `ai` 权限。不提交事务。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AgentMemory, AgentQuestion, AgentSession, User
from app.domain import sharing
from app.domain.agent import memory as agent_memory
from app.domain.agent import plan as agent_plan
from app.domain.agent import questions as agent_questions
from app.domain.agent.sessions import SHARE_KIND, readable_session, writable_session
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm

#: 会话列表最多给多少条(最近活跃在前)。
SESSION_LIST_LIMIT = 50


# ---------------- 会话 ----------------


def annotate(db: Session, user: User, session: AgentSession) -> AgentSession:
    """标上 `is_mine` / `shared` —— 界面据 `is_mine` 决定这条对话给不给写(共享来的只能看)。"""
    return sharing.annotate(db, SHARE_KIND, [session], user, session.workspace_id)[0]


def list_sessions(db: Session, user: User, workspace_id: str) -> list[AgentSession]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = (
        select(AgentSession)
        .where(
            AgentSession.workspace_id == workspace_id,
            AgentSession.origin == "ui",
            sharing.visible_filter(SHARE_KIND, user, workspace_id),
        )
        .order_by(AgentSession.updated_at.desc())
        .limit(SESSION_LIST_LIMIT)
    )
    return sharing.annotate(db, SHARE_KIND, list(db.scalars(stmt)), user, workspace_id)


def set_plan(db: Session, user: User, session_id: str, steps: list[Any]) -> AgentSession:
    """写这次会话的任务计划。空 = 清空(事情做完了)—— 没有出口的话,做完的计划会一直挂在面板上。

    直接执行、不走确认卡:写计划不改动任何工程状态。步骤不合规时抛 ValueError(说清怎么改)。
    """
    session = writable_session(db, user, session_id)
    session.plan = agent_plan.normalize(steps) if steps else None
    db.flush()
    return annotate(db, user, session)


def set_pending_view(db: Session, user: User, session_id: str, view: str, record_id: str = "") -> str:
    """智能体要求界面跳到哪儿。**待消费一次**,前端跳完就清(见 clear_pending_view)。"""
    session = writable_session(db, user, session_id)
    session.pending_view = f"{view}:{record_id}" if record_id else view
    return session.pending_view


def clear_pending_view(db: Session, user: User, session_id: str) -> None:
    """跳完了。清它也是写:那是主人的「带我过去」,看共享对话的同事不该替他消费掉。"""
    writable_session(db, user, session_id).pending_view = ""


# ---------------- 问用户 ----------------


def ask(db: Session, user: User, session_id: str, questions: list[dict[str, Any]]) -> AgentQuestion:
    """问题落在它那次对话里,往里问是写 —— 和发消息同一道闸。工作区跟着对话走,不由调用方另报。"""
    session = writable_session(db, user, session_id)
    return agent_questions.ask(db, workspace_id=session.workspace_id, session_id=session.id, questions=questions)


def _question_row(db: Session, question_id: str) -> AgentQuestion:
    """只管存在性。看不看得见、能不能答,跟着它所在的那次对话走 —— 调用方接着过读闸或写闸。"""
    row = db.get(AgentQuestion, question_id)
    if row is None:
        raise NotVisible("routeErr_questionNotFound")
    return row


def question(db: Session, user: User, question_id: str) -> AgentQuestion:
    row = _question_row(db, question_id)
    readable_session(db, user, row.session_id)
    return row


def pending_questions(db: Session, user: User, session_id: str) -> list[AgentQuestion]:
    """某次对话里还没答的问题。**按会话取,不按工作区** —— 一个问题脱离上下文没有意义。"""
    return agent_questions.pending_for(db, readable_session(db, user, session_id).id)


def answer(db: Session, user: User, question_id: str, answers: dict[str, Any]) -> AgentQuestion:
    """作答会变成那次对话里的一条用户消息:是在里面写,只有主人。"""
    row = _question_row(db, question_id)
    writable_session(db, user, row.session_id)
    answered = agent_questions.answer(db, row, answers)
    agent_questions.deliver_to_session(db, answered, user)
    return answered


def dismiss(db: Session, user: User, question_id: str) -> AgentQuestion:
    """不想答。模型会收到「用户跳过了」并继续往下走,而不是卡在那儿等。"""
    row = _question_row(db, question_id)
    writable_session(db, user, row.session_id)
    dismissed = agent_questions.dismiss(db, row)
    agent_questions.deliver_to_session(db, dismissed, user)
    return dismissed


# ---------------- 跨会话记忆 ----------------
#
# 设置页与智能体共用这组用例:用户在设置里看到的清单,就是每轮注入模型的那一份。


def list_memories(db: Session, user: User, workspace_id: str, project_id: str | None = None) -> list[AgentMemory]:
    ensure_workspace_access(db, user, workspace_id)
    return agent_memory.list_memories(db, workspace_id, project_id or None)


def remember(
    db: Session, user: User, workspace_id: str, content: str, *, project_id: str | None = None, source: str = "user"
) -> AgentMemory:
    ensure_workspace_perm(db, user, workspace_id, "ai")
    row = agent_memory.remember(db, workspace_id, content, project_id=project_id, source=source)
    db.flush()
    return row


def update_memory(db: Session, user: User, memory_id: str, content: str) -> AgentMemory:
    row = agent_memory.get(db, memory_id)
    if row is None:
        raise NotVisible("Not found")
    ensure_workspace_perm(db, user, row.workspace_id, "ai")
    agent_memory.update(db, row, content)
    db.flush()
    return row


def forget(db: Session, user: User, memory_id: str) -> None:
    """已经不在了就当忘过了(幂等)。"""
    row = agent_memory.get(db, memory_id)
    if row is not None:
        ensure_workspace_perm(db, user, row.workspace_id, "ai")
        agent_memory.forget(db, row)
