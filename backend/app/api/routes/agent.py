from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path

import asyncio

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.i18n import tr
from app.domain.agent import autopilot, host
from app.domain.agent import stream as agent_stream
from app.domain import sharing
from app.api.deps import CurrentUser, DbSession
from app.api.schemas import (
    AgentPendingView,
    AgentSpeechRequest,
    AgentManifestOut,
    AgentMemoryCreate,
    AgentMemoryOut,
    AgentQuestionAnswer,
    AgentQuestionCreate,
    AgentQuestionOut,
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
    AgentStreamEvent,
    ProviderUsageEventOut,
)
from app.core.config import app_version
from app.domain.permissions import ensure_workspace_access, ensure_workspace_perm
from app.db.models import AgentMessage, AgentQuestion, AgentSession, AgentVoicePref, ProviderProfile, ProviderUsageEvent, now
from app.domain.agent import list_agent_skills
from app.domain import session_groups
from app.domain.agent import memory as agent_memory
from app.domain.agent import questions as agent_questions
from app.domain.agent import plan as agent_plan
from app.domain.agent.sessions import SHARE_KIND, readable_session, writable_session

router = APIRouter(tags=["agent"])


def _checked_profile_id(db: DbSession, user: CurrentUser, profile_id: str | None) -> str | None:
    """会话钉在哪条连接上。**不存在就当场说不存在,不要留给数据库去炸。**

    provider_profile_id 是外键。给一个不存在的 id(界面开着时被另一处删掉、客户端拿着过期的
    id、或者有人手抄时截断了),插入会以 FOREIGN KEY constraint failed 结束 —— 接口回的是
    一个裸 500,既不说是哪个字段,也不说该怎么办,还会在监控里记成服务端故障。

    **不要求它是启用的**:停用只是「暂时别用」,把会话钉在上面仍然合理(运行时 resolve_chat_provider
    自己会回退到默认连接)。这里挡的只是「指向一条根本不存在、或者不属于你的连接」。
    """
    wanted = (profile_id or "").strip()
    if not wanted:
        return None
    profile = db.get(ProviderProfile, wanted)
    # 连接归人。别人的和不存在的对他是同一件事 —— 分开说等于确认了这个 id 有效。
    if profile is None or (profile.owner_user_id is not None and profile.owner_user_id != user.id):
        raise HTTPException(status_code=422, detail=tr("routeErr_aiConnectionNotFound"))
    return profile.id


@router.post("/agent/sessions", response_model=AgentSessionOut)
def create_agent_session(body: AgentSessionCreate, db: DbSession, user: CurrentUser) -> AgentSession:
    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    session = host.create_session(
        db,
        workspace_id=body.workspace_id,
        project_id=body.project_id,
        title=body.title,
        adapter=body.adapter,
        provider_profile_id=_checked_profile_id(db, user, body.provider_profile_id),
        model=body.model,
    )
    # 对话是**他的** —— 默认不共享给工作区(见 domain/sharing.KINDS)。
    sharing.claim(db, SHARE_KIND, session, user)
    db.commit()
    return _out(db, user, session)


@router.get("/agent/sessions", response_model=list[AgentSessionOut])
def list_agent_sessions(workspace_id: str, db: DbSession, user: CurrentUser) -> list[AgentSession]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = (
        select(AgentSession)
        .where(
            AgentSession.workspace_id == workspace_id,
            AgentSession.origin == "ui",
            sharing.visible_filter(SHARE_KIND, user, workspace_id),
        )
        # 手动位次优先,其次最近活跃。全是 0(没人拖过)时就是纯粹的"最近活跃在前"。
        .order_by(AgentSession.updated_at.desc())
        .limit(50)
    )
    return sharing.annotate(db, SHARE_KIND, list(db.scalars(stmt)), user, workspace_id)


def _out(db: DbSession, user: CurrentUser, session: AgentSession) -> AgentSession:
    """回出去的那一份标上 `is_mine` / `shared` —— 界面据 `is_mine` 决定这条对话给不给写(共享来的只能看)。"""
    return sharing.annotate(db, SHARE_KIND, [session], user, session.workspace_id)[0]


@router.get("/agent/sessions/{session_id}/messages", response_model=list[AgentMessageOut])
def list_agent_messages(session_id: str, db: DbSession, user: CurrentUser) -> list[AgentMessage]:
    session = readable_session(db, user, session_id)
    stmt = select(AgentMessage).where(AgentMessage.session_id == session.id).order_by(AgentMessage.created_at)
    return list(db.scalars(stmt))


@router.get("/agent/sessions/{session_id}/usage-events", response_model=list[ProviderUsageEventOut])
def list_agent_usage_events(session_id: str, db: DbSession, user: CurrentUser) -> list[ProviderUsageEvent]:
    session = readable_session(db, user, session_id)
    stmt = (
        select(ProviderUsageEvent)
        .join(AgentMessage, ProviderUsageEvent.agent_message_id == AgentMessage.id)
        .where(AgentMessage.session_id == session.id)
        .order_by(ProviderUsageEvent.created_at.asc())
    )
    return list(db.scalars(stmt))


@router.get("/agent/sessions/{session_id}", response_model=AgentSessionOut)
def get_agent_session(session_id: str, db: DbSession, user: CurrentUser) -> AgentSessionOut:
    session = _out(db, user, readable_session(db, user, session_id))
    out = AgentSessionOut.model_validate(session)
    context = host.session_context(db, session)
    out.context = AgentContextOut.model_validate(context) if context else None
    return out


@router.post("/agent/sessions/{session_id}/messages", response_model=AgentMessageOut)
def post_agent_message(
    session_id: str, body: AgentMessageCreate, db: DbSession, user: CurrentUser
) -> AgentMessage:
    session = writable_session(db, user, session_id)
    try:
        return host.post_user_message(
            db,
            session,
            body.content,
            user,
            context=body.context,
            references=[reference.model_dump() for reference in body.references],
            body_document=body.body_document,
            origin_session_id=body.origin_session_id,
        )
    except host.HostError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/agent/sessions/{session_id}/compact", response_model=AgentCompactOut)
def compact_agent_session(session_id: str, db: DbSession, user: CurrentUser) -> AgentCompactOut:
    """手动整理上下文。压缩要调一次模型做摘要,所以是用户主动触发,不做后台自动跑。"""
    session = writable_session(db, user, session_id)
    try:
        result = host.compact_session_context(db, session, user)
    except host.SidecarError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AgentCompactOut(**result)


@router.get("/agent/sessions/{session_id}/queue", response_model=list[AgentMessageOut])
def list_queued_messages(session_id: str, db: DbSession, user: CurrentUser) -> list[AgentMessage]:
    """Messages waiting behind the current answer. Empty when nothing is running."""
    session = readable_session(db, user, session_id)
    return host.queued_messages(db, session)


@router.post("/agent/sessions/{session_id}/queue/{message_id}/steer")
def steer_queued_message(session_id: str, message_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Cut a queued message into the running turn instead of letting it wait.

    The opt-in half of the pair: queuing is what happens by default, steering is a deliberate
    "change what you are doing now".
    """
    session = writable_session(db, user, session_id)
    try:
        return {"steered": host.steer_queued_message(db, session, message_id, user)}
    except host.HostError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/agent/sessions/{session_id}/queue/{message_id}")
def cancel_queued_message(session_id: str, message_id: str, db: DbSession, user: CurrentUser) -> dict:
    """Withdraw a queued message. Deleting the row alone is not enough — the model already
    holds it, so the turn's queue is resent without it."""
    session = writable_session(db, user, session_id)
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
    session = writable_session(db, user, session_id)
    return {"stopped": host.stop_turn(db, session)}


@router.patch("/agent/sessions/{session_id}", response_model=AgentSessionOut)
def update_agent_session(session_id: str, body: AgentSessionUpdate, db: DbSession, user: CurrentUser) -> AgentSession:
    session = writable_session(db, user, session_id)
    # 只改了分组就不算活动(见 session_groups.restore_updated_at)。
    organising_only = body.model_fields_set <= {"group_id"} and body.group_id is not None
    kept_updated_at = session.updated_at
    if body.title is not None:
        session.title = body.title
    if body.provider_profile_id is not None:
        session.provider_profile_id = _checked_profile_id(db, user, body.provider_profile_id)
    if body.model is not None:
        session.model = body.model or None
    if body.analysis_video_mode is not None:
        if body.analysis_video_mode not in ("auto", "native", "frames"):
            raise HTTPException(status_code=422, detail=tr("routeErr_badAnalysisVideoMode"))
        session.analysis_video_mode = body.analysis_video_mode
    if body.thinking_level is not None:
        if body.thinking_level not in ("off", "low", "medium", "high"):
            raise HTTPException(status_code=422, detail=tr("routeErr_badThinkingLevel"))
        session.thinking_level = body.thinking_level
    if body.permission_mode is not None:
        try:
            autopilot.set_permission_mode(db, user, session, body.permission_mode)
        except autopilot.PermissionModeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.group_id is not None:
        session_groups.move_into(db, session, body.group_id, kind="agent")
    if body.auto_allow_tools is not None:
        # 记下是谁定的:与模式同一条规则 —— 授权只对做出授权的那个人生效(见 domain/agent/autopilot)。
        session.auto_allow_tools = [str(name) for name in body.auto_allow_tools][:40]
        session.mode_set_by = user.id
        if session.mode_set_at is None:
            session.mode_set_at = now()
    db.commit()
    if organising_only:
        session_groups.restore_updated_at(db, session, kept_updated_at)
        db.commit()
    db.refresh(session)
    return _out(db, user, session)


@router.delete("/agent/sessions/{session_id}", status_code=204)
def delete_agent_session(session_id: str, db: DbSession, user: CurrentUser) -> Response:
    session = writable_session(db, user, session_id)
    sharing.forget(db, "agent_session", session.id)
    db.delete(session)
    db.commit()
    return Response(status_code=204)


@router.get("/agent/sessions/{session_id}/stream", response_model=AgentStreamEvent)
async def stream_agent_turn(session_id: str, db: DbSession, user: CurrentUser) -> StreamingResponse:
    """SSE: live token stream of the in-flight turn (snapshots, then done).

    `response_model` 在这里**只为把帧的形状写进 openapi**:返回的是 `StreamingResponse`,
    FastAPI 对直接返回的 Response 不做序列化,所以它不影响流本身。有了它,前端两个消费者
    就从生成类型取形状,不再各写一份 `as {...}` 断言 —— 那两份此前已经不一样了。
    """
    readable_session(db, user, session_id)

    async def generator():
        last_seq = -1
        while True:
            state = agent_stream.get_stream_state(session_id)
            if state["seq"] != last_seq:
                last_seq = state["seq"]
                yield (
                    "data: "
                    + AgentStreamEvent(
                        text=state["text"],
                        done=state["done"],
                        timeline=state.get("timeline", []),
                    ).model_dump_json()
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


@router.put("/agent/sessions/{session_id}/plan", response_model=AgentSessionOut)
def set_agent_plan(session_id: str, body: AgentPlanUpdate, db: DbSession, user: CurrentUser) -> AgentSession:
    """写这次会话的任务计划。

    直接执行、不走确认卡:写计划不改动任何工程状态。每一步都要点一次确认的计划没有人会用,
    而真正的改动(改时间线、导出、生成)仍然各自出卡。
    """
    session = writable_session(db, user, session_id)
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
    return _out(db, user, session)


# ---------- 跨会话记忆 ----------
#
# 设置页与智能体共用这组接口:用户在设置里看到的清单,就是每轮注入模型的那一份。
# 两份清单会立刻漂移,而"模型到底记住了什么"是用户唯一想确认的事。


@router.post("/agent/questions", response_model=AgentQuestionOut, status_code=201)
def ask_question(body: AgentQuestionCreate, db: DbSession, user: CurrentUser) -> AgentQuestion:
    """智能体问用户一个有选项的问题。

    问题落在它那次对话里,往里问是写 —— 和发消息同一道闸(共享来的对话只能看)。工作区跟着对话走,
    不由调用方另报一个:此前 MCP 那一侧缺省报的是「他的第一个工作区」,对话在别的工作区时,问题就
    记在了另一个工作区名下。
    """
    session = writable_session(db, user, body.session_id)
    try:
        return agent_questions.ask(
            db, workspace_id=session.workspace_id, session_id=session.id, questions=body.questions
        )
    except agent_questions.QuestionError as exc:
        # 422 而不是 500:这是模型给错了形状,消息里说清怎么改 —— 它下一步就是改了重发。
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/agent/questions/{question_id}", response_model=AgentQuestionOut)
def read_question(question_id: str, db: DbSession, user: CurrentUser) -> AgentQuestion:
    row = _question(db, question_id)
    readable_session(db, user, row.session_id)
    return row


@router.get("/agent/questions", response_model=list[AgentQuestionOut])
def list_pending_questions(session_id: str, db: DbSession, user: CurrentUser) -> list[AgentQuestion]:
    """某次对话里还没答的问题。**按会话取,不按工作区** —— 一个问题脱离上下文没有意义。"""
    session = readable_session(db, user, session_id)
    return agent_questions.pending_for(db, session.id)


@router.post("/agent/questions/{question_id}/answer", response_model=AgentQuestionOut)
def answer_question(
    question_id: str, body: AgentQuestionAnswer, db: DbSession, user: CurrentUser
) -> AgentQuestion:
    row = _question(db, question_id)
    # 作答会变成那次对话里的一条用户消息(deliver_to_session):是在里面写,只有主人。
    writable_session(db, user, row.session_id)
    try:
        answered = agent_questions.answer(db, row, body.answers)
    except agent_questions.QuestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    # 选完要有下文。应用自己那条路上模型正停在工具调用里等着,这一送是**兜底** ——
    # 等待有上限、直连 MCP 的客户端不阻塞、后端重启会掐掉那一轮(见 deliver_to_session)。
    agent_questions.deliver_to_session(db, answered, user)
    return answered


@router.post("/agent/questions/{question_id}/dismiss", response_model=AgentQuestionOut)
def dismiss_question(question_id: str, db: DbSession, user: CurrentUser) -> AgentQuestion:
    """不想答。模型会收到「用户跳过了」并继续往下走,而不是卡在那儿等。

    「收到」由两条路保证:应用自己那条运行时停在 ask_user 这次工具调用上等着,跳过就是它的
    返回值;而那一轮已经不在了的时候(等待到点、直连 MCP、后端重启过),由这里送过去。
    """
    row = _question(db, question_id)
    writable_session(db, user, row.session_id)
    dismissed = agent_questions.dismiss(db, row)
    agent_questions.deliver_to_session(db, dismissed, user)
    return dismissed


def _question(db: DbSession, question_id: str) -> AgentQuestion:
    """只管存在性。看不看得见、能不能答,跟着它所在的那次对话走 —— 调用方接着过读闸或写闸。"""
    row = db.get(AgentQuestion, question_id)
    if row is None:
        raise HTTPException(status_code=404, detail=tr("routeErr_questionNotFound"))
    return row


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
def get_agent_skills(db: DbSession, user: CurrentUser) -> list[dict]:
    return list_agent_skills(db, user.id)


@router.get("/agent/manifest", response_model=AgentManifestOut)
def get_agent_manifest(db: DbSession, user: CurrentUser) -> AgentManifestOut:
    return AgentManifestOut(
        app="mosael",
        version=app_version(),
        openapi_url="/openapi.json",
        skills=[AgentSkillOut.model_validate(skill) for skill in list_agent_skills(db, user.id)],
    )


@router.post("/agent/speech")
def speak(body: AgentSpeechRequest, db: DbSession, user: CurrentUser) -> Response:
    """念一句话,把音频**直接回给调用方**。

    **不建任务、不入素材库。** 对话里念出来的每一句都登记成素材的话,说十句就是十个音频
    文件 —— 而它们说完就没用了。这和配音是两件事:配音的产出要留存、要进时间线,所以它
    走 job + register_file_asset;这里的产出活到播完为止。

    这条路同时给三件事用:消息底部的播放、确认卡与提问的语音化、失败出声。它们共用同一个
    音色配置(settings/agent-voice),因为对用户来说那就是"它的声音"。

    没设过音色就说没设 —— 不替他挑一个(同 provider-defaults 的立场);「让它出声」关着就不念。
    """
    from app.domain.voices import agent_voice

    # 念一句是**花钱的**(各家 TTS 按字符计费),所以要 ai 权限,和对话、生成同一档。
    # 记账挂在这个工作区上,那它就得先证明自己在这个工作区里能花钱。
    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    return _speak_with_agent_voice(db, user, body, agent_voice.require_enabled, source_type="agent_speech")


@router.post("/agent/speech/preview")
def preview_speech(body: AgentSpeechRequest, db: DbSession, user: CurrentUser) -> Response:
    """试听设置里存着的那份对话音色。**只要求选好,不要求开着** —— 试听是配置时听一下效果,
    而「先打开才能听」等于让人先对一个没听过的声音点头。

    和 /agent/speech 只差这道闸:合成走同一个 agent_voice.speak,听到的就是以后念给他的那个声音。
    """
    from app.domain.voices import agent_voice

    # 试听照样花钱、照样记账:权限和真念同一档。
    ensure_workspace_perm(db, user, body.workspace_id, "ai")
    return _speak_with_agent_voice(db, user, body, agent_voice.require_ready, source_type="agent_voice_preview")


def _speak_with_agent_voice(
    db: DbSession,
    user: CurrentUser,
    body: AgentSpeechRequest,
    require: Callable[[Session, str], AgentVoicePref],
    *,
    source_type: str,
) -> Response:
    """两条发声路共用的后半段:取配置(闸由 `require` 定)、合成、原样回音频。ai 权限由调用方先查。"""
    from app.domain.voices import agent_voice

    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail=tr("routeErr_nothingToRead"))
    try:
        pref = require(db, user.id)
    except agent_voice.AgentVoiceUnavailable as exc:
        # 409 而不是 500:这是"还没配好 / 关着",一个用户点两下就能解决的状态。
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    with tempfile.TemporaryDirectory(prefix="mosael-say-") as tmp:
        try:
            out = agent_voice.speak(
                db, pref, text=text, workspace_id=body.workspace_id, out_dir=Path(tmp), source_type=source_type
            )
        except Exception as exc:  # noqa: BLE001 — 合成失败是结果,不是服务端故障
            raise HTTPException(status_code=422, detail=str(exc)[:300]) from exc
        audio = out.read_bytes()
        media_type = "audio/mpeg" if out.suffix == ".mp3" else "audio/wav"
    return Response(content=audio, media_type=media_type, headers={"Cache-Control": "no-store"})


@router.post("/agent/sessions/{session_id}/view")
def set_pending_view(session_id: str, body: AgentPendingView, db: DbSession, user: CurrentUser) -> dict[str, str]:
    """智能体要求界面跳到哪儿。**待消费一次**,前端跳完就清。

    方向是反的:智能体跑在后端,而切页面是前端的事。落在会话行上而不是流里 —— 前端本来就在
    轮询会话状态,而免提浮标那种没开 SSE 的场景照样收得到,那恰恰是"带我过去"最有用的时候。
    """
    session = writable_session(db, user, session_id)
    session.pending_view = f"{body.view}:{body.id}" if body.id else body.view
    db.commit()
    return {"pending_view": session.pending_view}


@router.delete("/agent/sessions/{session_id}/view", status_code=204)
def clear_pending_view(session_id: str, db: DbSession, user: CurrentUser) -> Response:
    """跳完了。**由前端来清,不是读一次就清** —— 读了就清的话,两个开着的界面里
    只有先读到的那个会跳,而另一个永远不知道发生过什么。

    清它也是写:那是主人的「带我过去」,看共享对话的同事不该替他消费掉(界面上只读会话不跳)。"""
    session = writable_session(db, user, session_id)
    session.pending_view = ""
    db.commit()
    return Response(status_code=204)
