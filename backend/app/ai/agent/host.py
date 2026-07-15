from __future__ import annotations

import logging
import os
import threading
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agent.adapters import AdapterError, TurnResult, run_turn
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import new_session_token
from app.db.models import AgentMessage, AgentSession, AuthSession, User, now

"""
Agent host (plan §16 + user decision): sessions and messages live in Mibu;
each turn drives a specialized external agent CLI whose only write path into
Mibu is the MCP tool surface guarded by confirmation cards.
"""

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """你是 Mibu 的视频创作助手,运行在用户本机的 Mibu 工作台里。
你唯一的工作对象是 Mibu 里的素材、时间线与生成能力,通过 mibu MCP 工具操作:
- 侦查用 list_projects / list_assets / inspect_sequence(只读,随时可用)。
- 修改时间线用 edit_timeline,导出用 render_sequence,生成素材用 generate_image / generate_video。
  这些工具只会创建“确认卡”,用户在 Mibu 界面批准后才会执行;创建后用 get_confirmation 轮询结果。
- 提出修改前先 inspect_sequence 看清现状;修改后告诉用户你提交了什么等待确认。
- 所有已批准的时间线修改用户都可以撤销,不必过度谨慎,但一次确认卡只装一个连贯意图。
工作区 ID: {workspace_id}。用用户使用的语言回复,简洁、面向创作者,不要提及内部实现细节。
不要读写本机文件系统,不要执行 shell 命令;只使用 mibu 工具与对话。"""

_turn_callbacks: list[Callable[[str], None]] = []


def on_turn_finished(callback: Callable[[str], None]) -> None:
    """Register a listener (e.g. the Feishu worker) fired with session_id after each turn."""
    _turn_callbacks.append(callback)


def default_adapter() -> str:
    return os.environ.get("MIBU_AGENT_CLI", "claude")


def create_session(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None = None,
    origin: str = "ui",
    external_key: str | None = None,
    title: str = "新对话",
    adapter: str | None = None,
) -> AgentSession:
    session = AgentSession(
        workspace_id=workspace_id,
        project_id=project_id,
        origin=origin,
        external_key=external_key,
        title=title,
        adapter=adapter or default_adapter(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_or_create_external_session(db: Session, *, workspace_id: str, external_key: str, title: str) -> AgentSession:
    existing = db.scalar(select(AgentSession).where(AgentSession.external_key == external_key))
    if existing is not None:
        return existing
    return create_session(
        db, workspace_id=workspace_id, origin="feishu", external_key=external_key, title=title
    )


class HostError(RuntimeError):
    pass


def post_user_message(db: Session, session: AgentSession, content: str, user: User) -> AgentMessage:
    """Store the user message and run the agent turn on a worker thread."""
    if session.status == "running":
        raise HostError("Session already has a turn in flight")
    message = AgentMessage(session_id=session.id, role="user", content=content)
    session.status = "running"
    if session.title == "新对话" and content.strip():
        session.title = content.strip()[:60]
    db.add(message)
    db.commit()

    token = _mint_service_token(db, user)
    threading.Thread(target=_run_turn_thread, args=(session.id, content, token), daemon=True).start()
    db.refresh(message)
    return message


def _mint_service_token(db: Session, user: User) -> str:
    token = new_session_token()
    db.add(AuthSession(token=token, user_id=user.id))
    db.commit()
    return token


def _run_turn_thread(session_id: str, prompt: str, token: str) -> None:
    api_base = f"http://{settings.backend_host}:{settings.backend_port}"
    with SessionLocal() as db:
        session = db.get(AgentSession, session_id)
        if session is None:
            return
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(workspace_id=session.workspace_id)
        try:
            result: TurnResult = run_turn(
                session.adapter,
                prompt=prompt,
                system_prompt=system_prompt,
                api_base=api_base,
                token=token,
                adapter_session_id=session.adapter_session_id,
            )
            db.add(AgentMessage(session_id=session.id, role="assistant", content=result.text))
            if result.adapter_session_id:
                session.adapter_session_id = result.adapter_session_id
        except AdapterError as exc:
            db.add(
                AgentMessage(
                    session_id=session.id,
                    role="assistant",
                    content="智能体执行失败，请稍后重试。",
                    error=str(exc)[:800],
                )
            )
        except Exception as exc:  # worker threads must never die silently
            logger.exception("Agent turn crashed")
            db.add(
                AgentMessage(
                    session_id=session.id, role="assistant", content="智能体执行异常。", error=str(exc)[:800]
                )
            )
        finally:
            session.status = "idle"
            session.updated_at = now()
            db.commit()
    for callback in list(_turn_callbacks):
        try:
            callback(session_id)
        except Exception:
            logger.exception("Turn callback failed")
