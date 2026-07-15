from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.ai.agent import host
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    AgentManifestOut,
    AgentMessageCreate,
    AgentMessageOut,
    AgentSessionCreate,
    AgentSessionOut,
    AgentSkillOut,
)
from app.core.permissions import ensure_workspace_access
from app.db.models import AgentMessage, AgentSession
from app.domain.agent import list_agent_skills

router = APIRouter(tags=["agent"])


@router.post("/agent/sessions", response_model=AgentSessionOut)
def create_agent_session(body: AgentSessionCreate, db: DbSession, user: CurrentUser) -> AgentSession:
    ensure_workspace_access(db, user, body.workspace_id)
    return host.create_session(
        db,
        workspace_id=body.workspace_id,
        project_id=body.project_id,
        title=body.title,
        adapter=body.adapter,
    )


@router.get("/agent/sessions", response_model=list[AgentSessionOut])
def list_agent_sessions(workspace_id: str, db: DbSession, user: CurrentUser) -> list[AgentSession]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = (
        select(AgentSession)
        .where(AgentSession.workspace_id == workspace_id, AgentSession.origin == "ui")
        .order_by(AgentSession.updated_at.desc())
        .limit(50)
    )
    return list(db.scalars(stmt))


@router.get("/agent/sessions/{session_id}/messages", response_model=list[AgentMessageOut])
def list_agent_messages(session_id: str, db: DbSession, user: CurrentUser) -> list[AgentMessage]:
    session = _require_session(db, user, session_id)
    stmt = select(AgentMessage).where(AgentMessage.session_id == session.id).order_by(AgentMessage.created_at)
    return list(db.scalars(stmt))


@router.get("/agent/sessions/{session_id}", response_model=AgentSessionOut)
def get_agent_session(session_id: str, db: DbSession, user: CurrentUser) -> AgentSession:
    return _require_session(db, user, session_id)


@router.post("/agent/sessions/{session_id}/messages", response_model=AgentMessageOut)
def post_agent_message(
    session_id: str, body: AgentMessageCreate, db: DbSession, user: CurrentUser
) -> AgentMessage:
    session = _require_session(db, user, session_id)
    try:
        return host.post_user_message(db, session, body.content, user)
    except host.HostError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/agent/sessions/{session_id}/stream")
async def stream_agent_turn(session_id: str, db: DbSession, user: CurrentUser) -> StreamingResponse:
    """SSE: live token stream of the in-flight turn (snapshots, then done)."""
    _require_session(db, user, session_id)

    async def generator():
        last_seq = -1
        while True:
            state = host.get_stream_state(session_id)
            if state["seq"] != last_seq:
                last_seq = state["seq"]
                yield f"data: {json.dumps({'text': state['text'], 'done': state['done']})}\n\n"
            if state["done"]:
                break
            await asyncio.sleep(0.1)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _require_session(db: DbSession, user: CurrentUser, session_id: str) -> AgentSession:
    session = db.get(AgentSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Not found")
    ensure_workspace_access(db, user, session.workspace_id)
    return session


@router.get("/agent/skills", response_model=list[AgentSkillOut])
def get_agent_skills(db: DbSession) -> list[dict]:
    return list_agent_skills(db)


@router.get("/agent/manifest", response_model=AgentManifestOut)
def get_agent_manifest(db: DbSession) -> AgentManifestOut:
    return AgentManifestOut(
        app="mibu-new",
        version="0.1.0",
        openapi_url="/openapi.json",
        skills=[AgentSkillOut.model_validate(skill) for skill in list_agent_skills(db)],
    )
