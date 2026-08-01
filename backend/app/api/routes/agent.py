from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.ai.agent import host
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    AgentManifestOut,
    AgentMessageCreate,
    AgentCompactOut,
    AgentMessageOut,
    AgentSessionCreate,
    AgentSessionOut,
    AgentSessionUpdate,
    AgentSkillOut,
    ProviderUsageEventOut,
)
from app.core.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import AgentMessage, AgentSession, ProviderUsageEvent
from app.domain.agent import list_agent_skills

router = APIRouter(tags=["agent"])


@router.post("/agent/sessions", response_model=AgentSessionOut)
def create_agent_session(body: AgentSessionCreate, db: DbSession, user: CurrentUser) -> AgentSession:
    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    return host.create_session(
        db,
        workspace_id=body.workspace_id,
        project_id=body.project_id,
        title=body.title,
        adapter=body.adapter,
        provider_profile_id=body.provider_profile_id,
        model=body.model,
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


@router.get("/agent/sessions/{session_id}/usage-events", response_model=list[ProviderUsageEventOut])
def list_agent_usage_events(session_id: str, db: DbSession, user: CurrentUser) -> list[ProviderUsageEvent]:
    session = _require_session(db, user, session_id)
    stmt = (
        select(ProviderUsageEvent)
        .join(AgentMessage, ProviderUsageEvent.agent_message_id == AgentMessage.id)
        .where(AgentMessage.session_id == session.id)
        .order_by(ProviderUsageEvent.created_at.asc())
    )
    return list(db.scalars(stmt))


@router.get("/agent/sessions/{session_id}", response_model=AgentSessionOut)
def get_agent_session(session_id: str, db: DbSession, user: CurrentUser) -> AgentSession:
    return _require_session(db, user, session_id)


@router.post("/agent/sessions/{session_id}/messages", response_model=AgentMessageOut)
def post_agent_message(
    session_id: str, body: AgentMessageCreate, db: DbSession, user: CurrentUser
) -> AgentMessage:
    session = _require_session(db, user, session_id)
    ensure_workspace_perm(db, user, session.workspace_id, "ai")
    try:
        return host.post_user_message(db, session, body.content, user, context=body.context)
    except host.HostError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/agent/sessions/{session_id}/compact", response_model=AgentCompactOut)
def compact_agent_session(session_id: str, db: DbSession, user: CurrentUser) -> AgentCompactOut:
    """手动整理上下文。压缩要调一次模型做摘要,所以是用户主动触发,不做后台自动跑。"""
    session = _require_session(db, user, session_id)
    ensure_workspace_perm(db, user, session.workspace_id, "ai")
    try:
        result = host.compact_session_context(db, session, user)
    except host.AdapterError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AgentCompactOut(**result)


@router.get("/agent/sessions/{session_id}/queue", response_model=list[AgentMessageOut])
def list_queued_messages(session_id: str, db: DbSession, user: CurrentUser) -> list[AgentMessage]:
    """Messages waiting behind the current answer. Empty when nothing is running."""
    session = _require_session(db, user, session_id)
    return host.queued_messages(db, session)


@router.post("/agent/sessions/{session_id}/queue/{message_id}/steer")
def steer_queued_message(session_id: str, message_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Cut a queued message into the running turn instead of letting it wait.

    The opt-in half of the pair: queuing is what happens by default, steering is a deliberate
    "change what you are doing now".
    """
    session = _require_session(db, user, session_id)
    ensure_workspace_perm(db, user, session.workspace_id, "ai")
    try:
        return {"steered": host.steer_queued_message(db, session, message_id, user)}
    except host.HostError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/agent/sessions/{session_id}/queue/{message_id}")
def cancel_queued_message(session_id: str, message_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Withdraw a queued message. Deleting the row alone is not enough — the model already
    holds it, so the turn's queue is resent without it."""
    session = _require_session(db, user, session_id)
    ensure_workspace_perm(db, user, session.workspace_id, "ai")
    try:
        remaining = host.cancel_queued_message(db, session, message_id)
    except host.HostError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"remaining": len(remaining)}


@router.post("/agent/sessions/{session_id}/stop")
def stop_agent_turn(session_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Stop the running turn, keeping the partial answer.

    Not an error when nothing is running: the user pressing stop just as a turn finishes is
    a race they cannot see, and an error toast for it would be noise.
    """
    session = _require_session(db, user, session_id)
    ensure_workspace_perm(db, user, session.workspace_id, "ai")
    return {"stopped": host.stop_turn(db, session)}


@router.patch("/agent/sessions/{session_id}", response_model=AgentSessionOut)
def update_agent_session(session_id: str, body: AgentSessionUpdate, db: DbSession, user: CurrentUser) -> AgentSession:
    session = _require_session(db, user, session_id)
    if body.title is not None:
        session.title = body.title
    if body.provider_profile_id is not None:
        session.provider_profile_id = body.provider_profile_id or None
    if body.model is not None:
        session.model = body.model or None
    if body.analysis_video_mode is not None:
        if body.analysis_video_mode not in ("auto", "native", "frames"):
            raise HTTPException(status_code=422, detail="analysis_video_mode 只能是 auto/native/frames")
        session.analysis_video_mode = body.analysis_video_mode
    db.commit()
    db.refresh(session)
    return session


@router.delete("/agent/sessions/{session_id}", status_code=204)
def delete_agent_session(session_id: str, db: DbSession, user: CurrentUser) -> Response:
    session = _require_session(db, user, session_id)
    db.delete(session)
    db.commit()
    return Response(status_code=204)


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
                yield (
                    "data: "
                    + json.dumps(
                        {
                            "text": state["text"],
                            "done": state["done"],
                            "timeline": state.get("timeline", []),
                        }
                    )
                    + "\n\n"
                )
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
        app="open-studio",
        version="0.1.0",
        openapi_url="/openapi.json",
        skills=[AgentSkillOut.model_validate(skill) for skill in list_agent_skills(db)],
    )
