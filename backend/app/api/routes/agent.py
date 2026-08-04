from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.ai.agent import host
from app.domain import sharing
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    AgentManifestOut,
    AgentMemoryCreate,
    AgentMemoryOut,
    AgentMemoryUpdate,
    AgentPlanUpdate,
    AgentMessageCreate,
    AgentCompactOut,
    AgentContextOut,
    AgentMessageOut,
    AgentSessionCreate,
    AgentSessionOut,
    AgentSessionUpdate,
    AgentSkillOut,
    ProviderUsageEventOut,
)
from app.core.config import app_version
from app.core.permissions import ensure_workspace_access, ensure_workspace_perm, ensure_workspace_role
from app.db.models import AgentMessage, AgentSession, ProviderUsageEvent, now
from app.domain.agent import list_agent_skills
from app.domain.agent import memory as agent_memory
from app.domain.agent import plan as agent_plan

router = APIRouter(tags=["agent"])


@router.post("/agent/sessions", response_model=AgentSessionOut)
def create_agent_session(body: AgentSessionCreate, db: DbSession, user: CurrentUser) -> AgentSession:
    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    session = host.create_session(
        db,
        workspace_id=body.workspace_id,
        project_id=body.project_id,
        title=body.title,
        adapter=body.adapter,
        provider_profile_id=body.provider_profile_id,
        model=body.model,
    )
    # 对话是**他的** —— 默认不共享给工作区(见 domain/sharing.KINDS)。
    sharing.claim(db, "agent_session", session, user)
    db.commit()
    return sharing.annotate(db, "agent_session", [session], user, session.workspace_id)[0]


@router.get("/agent/sessions", response_model=list[AgentSessionOut])
def list_agent_sessions(workspace_id: str, db: DbSession, user: CurrentUser) -> list[AgentSession]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = (
        select(AgentSession)
        .where(
            AgentSession.workspace_id == workspace_id,
            AgentSession.origin == "ui",
            sharing.visible_filter("agent_session", user, workspace_id),
        )
        .order_by(AgentSession.updated_at.desc())
        .limit(50)
    )
    return sharing.annotate(db, "agent_session", list(db.scalars(stmt)), user, workspace_id)


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
def get_agent_session(session_id: str, db: DbSession, user: CurrentUser) -> AgentSessionOut:
    session = _require_session(db, user, session_id)
    out = AgentSessionOut.model_validate(session)
    context = host.session_context(db, session)
    out.context = AgentContextOut.model_validate(context) if context else None
    return out


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
    if body.thinking_level is not None:
        if body.thinking_level not in ("off", "low", "medium", "high"):
            raise HTTPException(status_code=422, detail="thinking_level 只能是 off/low/medium/high")
        session.thinking_level = body.thinking_level
    if body.permission_mode is not None:
        _set_permission_mode(db, user, session, body.permission_mode)
    if body.auto_allow_tools is not None:
        # 记下是谁定的:与模式同一条规则 —— 授权只对做出授权的那个人生效(见 domain/agent/autopilot)。
        ensure_workspace_perm(db, user, session.workspace_id, "ai")
        session.auto_allow_tools = [str(name) for name in body.auto_allow_tools][:40]
        session.mode_set_by = user.id
        if session.mode_set_at is None:
            session.mode_set_at = now()
    db.commit()
    db.refresh(session)
    return session


PERMISSION_MODES = ("manual", "auto", "bypass")


def _set_permission_mode(db: DbSession, user: CurrentUser, session: AgentSession, mode: str) -> None:
    """切换这次对话的权限模式。

    - 要 `ai` 权限:它决定的是"智能体能不问就做什么",和能不能用智能体是同一件事的两半。
    - **bypass 另要 admin**:它是「不问我就做」——发布、花钱、对外的动作都不再经过一次人眼。
      隔离执行器到位之后,"跑代码"本身已经不是提权(见 domain/sandbox),但**不问就做**仍然是
      一个工作区级别的决定,不是每个 editor 自己能给自己开的。
    - **飞书会话不给 bypass**:那是一个群里所有人共用的对话,而 bypass 不该由一个人替一群人开。
    - 记下**是谁开的**:授权只对做出授权的那个人生效(见 domain/agent/autopilot.decide)。
    """
    if mode not in PERMISSION_MODES:
        raise HTTPException(status_code=422, detail=f"permission_mode 只能是 {'/'.join(PERMISSION_MODES)}")
    ensure_workspace_perm(db, user, session.workspace_id, "ai")
    if mode == "bypass":
        if session.origin != "ui":
            raise HTTPException(status_code=403, detail="共享会话(如飞书)不能开 bypass —— 它不该由一个人替一群人开")
        ensure_workspace_role(db, user, session.workspace_id, "admin")
    session.permission_mode = mode
    session.mode_set_by = user.id
    session.mode_set_at = now()


@router.delete("/agent/sessions/{session_id}", status_code=204)
def delete_agent_session(session_id: str, db: DbSession, user: CurrentUser) -> Response:
    session = _require_session(db, user, session_id, perm="ai")
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


def _require_session(db: DbSession, user: CurrentUser, session_id: str, *, perm: str | None = None) -> AgentSession:
    session = db.get(AgentSession, session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Not found")
    if perm is None:
        ensure_workspace_access(db, user, session.workspace_id)
    else:
        ensure_workspace_perm(db, user, session.workspace_id, perm)
    # 看不见就是不存在(404,不是 403)—— 和工作区边界同一条口径,不泄露"这里有一个你看不到的东西"。
    if not sharing.may_use(db, "agent_session", session, user):
        raise HTTPException(status_code=404, detail="Not found")
    return session


@router.put("/agent/sessions/{session_id}/plan", response_model=AgentSessionOut)
def set_agent_plan(session_id: str, body: AgentPlanUpdate, db: DbSession, user: CurrentUser) -> AgentSession:
    """写这次会话的任务计划。

    直接执行、不走确认卡:写计划不改动任何工程状态。每一步都要点一次确认的计划没有人会用,
    而真正的改动(改时间线、导出、生成)仍然各自出卡。
    """
    session = _require_session(db, user, session_id)
    ensure_workspace_perm(db, user, session.workspace_id, "ai")
    if not body.steps:
        # 空数组 = 清空计划(事情做完了)。这不是错误输入 —— 没有出口的话,一份做完的计划
        # 会一直挂在面板上,而"还剩几步"是它唯一要回答的问题。
        session.plan = None
    else:
        try:
            session.plan = agent_plan.normalize(body.steps)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(session)
    return session


# ---------- 跨会话记忆 ----------
#
# 设置页与智能体共用这组接口:用户在设置里看到的清单,就是每轮注入模型的那一份。
# 两份清单会立刻漂移,而"模型到底记住了什么"是用户唯一想确认的事。


@router.get("/agent/memories", response_model=list[AgentMemoryOut])
def list_memories(workspace_id: str, db: DbSession, user: CurrentUser, project_id: str = "") -> list:
    ensure_workspace_access(db, user, workspace_id)
    return agent_memory.list_memories(db, workspace_id, project_id or None)


@router.post("/agent/memories", response_model=AgentMemoryOut, status_code=201)
def create_memory(body: AgentMemoryCreate, db: DbSession, user: CurrentUser):
    ensure_workspace_access(db, user, body.workspace_id)
    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    try:
        row = agent_memory.remember(
            db,
            body.workspace_id,
            body.content,
            project_id=body.project_id,
            source=body.source,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return row


@router.patch("/agent/memories/{memory_id}", response_model=AgentMemoryOut)
def update_memory(memory_id: str, body: AgentMemoryUpdate, db: DbSession, user: CurrentUser):
    row = agent_memory.get(db, memory_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Not found")
    ensure_workspace_access(db, user, row.workspace_id)
    ensure_workspace_perm(db, user, row.workspace_id, "ai")
    try:
        agent_memory.update(db, row, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(row)
    return row


@router.delete("/agent/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: str, db: DbSession, user: CurrentUser) -> None:
    row = agent_memory.get(db, memory_id)
    if row is None:
        return
    ensure_workspace_access(db, user, row.workspace_id)
    ensure_workspace_perm(db, user, row.workspace_id, "ai")
    agent_memory.forget(db, row)
    db.commit()


@router.get("/agent/skills", response_model=list[AgentSkillOut])
def get_agent_skills(db: DbSession) -> list[dict]:
    return list_agent_skills(db)


@router.get("/agent/manifest", response_model=AgentManifestOut)
def get_agent_manifest(db: DbSession) -> AgentManifestOut:
    return AgentManifestOut(
        app="open-studio",
        version=app_version(),
        openapi_url="/openapi.json",
        skills=[AgentSkillOut.model_validate(skill) for skill in list_agent_skills(db)],
    )
