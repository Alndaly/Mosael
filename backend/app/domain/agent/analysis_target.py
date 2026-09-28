"""智能体回连分析素材时,用哪条连接、哪个模型 —— 由**这次对话**决定,不由工具参数决定。

放在智能体这一侧:它读的是对话(AgentSession)和对话的连接解析(host.resolve_chat_provider),
而分析领域不该反过来认识智能体(agent.prompt 已经依赖 analysis)。
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.sidecar.adapters import AdapterError
from app.db.models import AgentSession
from app.domain.agent.host import resolve_chat_provider
from app.domain.analysis.service import AnalysisError
from app.domain.provider_credentials import ResolvedConnection


@dataclass(frozen=True)
class AgentSessionTarget:
    """智能体回连分析时,由它所在的那次对话决定的三样:连接、模型、视频看法。"""

    connection: ResolvedConnection
    model: str
    mode: str


def agent_session_target(db: Session, agent_session_id: str, *, workspace_id: str, user_id: str) -> AgentSessionTarget:
    """智能体工具回连时,分析用**这次对话**正在用的连接和模型。

    从服务端事实解析,不让模型在工具参数里自报 profile / model —— 那既可伪造,也可能摸到别人的
    连接。素材得在这次对话的工作区里。
    """
    session = db.get(AgentSession, agent_session_id)
    if session is None or session.workspace_id != workspace_id:
        raise AnalysisError("analysisErr_assetNotInAgentWorkspace")
    try:
        _provider, model, connection = resolve_chat_provider(
            db, session.provider_profile_id, session.model or "", user_id=user_id
        )
    except AdapterError as exc:
        raise AnalysisError.relay(exc) from exc
    return AgentSessionTarget(connection=connection, model=model, mode=session.analysis_video_mode or "auto")
