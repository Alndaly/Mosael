from __future__ import annotations

import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import asyncio

from fastapi import APIRouter, HTTPException, Response
from fastapi.responses import StreamingResponse

from app.api.responses import event_stream
from sqlalchemy import select

from app.core.i18n import tr
from app.domain.agent import autopilot, host
from app.domain.agent import stream as agent_stream
from app.domain import sharing
from app.api.deps import CurrentUser, DbSession, Tx
from app.domain.agent import use_cases as agent_use_cases
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
    AgentHomesMove,
    AgentHomesMoved,
    AgentMessageOut,
    AgentSessionCreate,
    AgentSessionOut,
    AgentSessionUpdate,
    AgentToolsetOut,
    AgentStreamEvent,
    ProviderUsageEventOut,
    SessionAllowance,
)
from app.core.config import app_version
from app.db.models import AgentMessage, AgentQuestion, AgentSession, ProviderUsageEvent
from app.domain.agent import list_agent_toolsets
from app.domain import session_groups
from app.domain.agent import places, titles
from app.domain.agent import questions as agent_questions
from app.domain.agent.sessions import readable_session, writable_session

router = APIRouter(tags=["agent"])


def _place(kind: str, place_id: str) -> places.Place:
    """形状不对的地方是 422 —— 说清哪里不对,不当成「没有这个东西」。"""
    try:
        return places.checked(kind, place_id)
    except places.PlaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _apply_settings(
    db: DbSession,
    user: CurrentUser,
    session: AgentSession,
    *,
    analysis_video_mode: str | None,
    thinking_level: str | None,
    permission_mode: str | None,
) -> None:
    """建会话(草稿上选好的)和改会话设置同一套校验:分析方式、思考档位、权限模式。给 None 的不动。"""
    if analysis_video_mode is not None:
        if analysis_video_mode not in ("auto", "native", "frames"):
            raise HTTPException(status_code=422, detail=tr("routeErr_badAnalysisVideoMode"))
        session.analysis_video_mode = analysis_video_mode
    if thinking_level is not None:
        if thinking_level not in ("off", "low", "medium", "high"):
            raise HTTPException(status_code=422, detail=tr("routeErr_badThinkingLevel"))
        session.thinking_level = thinking_level
    if permission_mode is not None:
        try:
            autopilot.set_permission_mode(db, user, session, permission_mode)
        except autopilot.PermissionModeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/agent/sessions", response_model=AgentSessionOut)
def create_agent_session(body: AgentSessionCreate, db: Tx, user: CurrentUser) -> AgentSession:
    """建一段对话 —— 界面上是第一句话发出去的那一刻(草稿在那之前不建)。草稿上选好的设置一起带上;哪一项不合规整个
    不建(同一个事务),不留下一段空对话。"""
    try:
        session = agent_use_cases.start_session(
            db,
            user,
            body.workspace_id,
            home=_place(body.home.kind, body.home.id),
            title=body.title,
            adapter=body.adapter,
            provider_profile_id=body.provider_profile_id,
            model=body.model,
        )
    except (agent_use_cases.UnknownConnection, places.PlaceError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    _apply_settings(
        db, user, session,
        analysis_video_mode=body.analysis_video_mode,
        thinking_level=body.thinking_level,
        permission_mode=body.permission_mode,
    )
    return session


@router.get("/agent/sessions", response_model=list[AgentSessionOut])
def list_agent_sessions(
    workspace_id: str, db: DbSession, user: CurrentUser, home_kind: str = "", home_id: str = ""
) -> list[AgentSession]:
    """不带 `home_kind` 列全部(AI Studio);带了只列家在那里的(各处面板的「这里的对话」,ADR 0044 §2)。"""
    home = _place(home_kind, home_id) if home_kind else None
    return agent_use_cases.list_sessions(db, user, workspace_id, home)


@router.post("/agent/homes/move", response_model=AgentHomesMoved)
def move_agent_homes(body: AgentHomesMove, db: Tx, user: CurrentUser) -> AgentHomesMoved:
    """ComfyUI 那张工作流存盘、改名、挪文件夹时,家跟着挪(ADR 0044 §9)。只收 `comfyui`,只挪他自己的对话。"""
    try:
        moved = agent_use_cases.move_homes(db, user, body.workspace_id, body.kind, body.from_id, body.to_id)
    except places.PlaceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgentHomesMoved(moved=moved)


def _out(db: DbSession, user: CurrentUser, session: AgentSession) -> AgentSession:
    """回出去的那一份标上 `is_mine` / `shared`(界面据 `is_mine` 决定这条对话给不给写)和家的名字、状况。"""
    return agent_use_cases.annotate(db, user, session)


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
            quote=body.quote.model_dump() if body.quote else None,
            skills=body.skills,
            place=_place(body.place.kind, body.place.id) if body.place else None,
        )
    except host.HostError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/agent/sessions/{session_id}/compact", response_model=AgentCompactOut)
def compact_agent_session(session_id: str, db: DbSession, user: CurrentUser) -> AgentCompactOut:
    """手动整理上下文。压缩要调一次模型做摘要,所以是用户主动触发,不做后台自动跑。"""
    session = writable_session(db, user, session_id)
    try:
        result = host.compact_session_context(db, session, user)
    except host.HostError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except host.SidecarError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return AgentCompactOut(**result)


@router.get("/agent/sessions/{session_id}/queue", response_model=list[AgentMessageOut])
def list_queued_messages(session_id: str, db: DbSession, user: CurrentUser) -> list[AgentMessage]:
    """Messages waiting behind the current answer. 按停止时扣下的那几条(payload 带 `held`)空闲时也在这里,等人点「继续发送」。"""
    session = readable_session(db, user, session_id)
    return host.queued_messages(db, session)


@router.post("/agent/sessions/{session_id}/queue/{message_id}/steer")
def steer_queued_message(session_id: str, message_id: str, db: Tx, user: CurrentUser) -> dict:
    """Cut a queued message into the running turn instead of letting it wait.

    The opt-in half of the pair: queuing is what happens by default, steering is a deliberate
    "change what you are doing now".
    """
    session = writable_session(db, user, session_id)
    try:
        return {"steered": host.steer_queued_message(db, session, message_id, user)}
    except host.HostError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/agent/sessions/{session_id}/queue/{message_id}/resume")
def resume_queued_message(session_id: str, message_id: str, db: Tx, user: CurrentUser) -> dict:
    """「继续发送」:按停止时扣下的那条放回队列 —— 这段对话空闲就当场开跑,正忙就排在这一轮后面(D63)。"""
    session = writable_session(db, user, session_id)
    try:
        host.resume_queued_message(db, session, message_id)
    except host.HostError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    host.drain_queue_after_commit(db, session.id)
    return {"resumed": True}


@router.delete("/agent/sessions/{session_id}/queue/{message_id}")
def cancel_queued_message(session_id: str, message_id: str, db: Tx, user: CurrentUser) -> dict:
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
        #: 人起的名字:之后不再替它起(见 domain/agent/titles)。
        session.title_source = titles.MANUAL
    if body.provider_profile_id is not None:
        try:
            session.provider_profile_id = agent_use_cases.checked_profile_id(db, user, body.provider_profile_id)
        except agent_use_cases.UnknownConnection as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    if body.model is not None:
        session.model = body.model or None
    _apply_settings(
        db, user, session,
        analysis_video_mode=body.analysis_video_mode,
        thinking_level=body.thinking_level,
        permission_mode=body.permission_mode,
    )
    if body.group_id is not None:
        session_groups.move_into(db, session, body.group_id, kind="agent")
    if body.auto_allow_tools is not None:
        with autopilot.ALLOWANCE_LOCK:
            try:
                autopilot.set_session_allowances(
                    db, user, session, [(entry.tool, entry.permission) for entry in body.auto_allow_tools]
                )
            except autopilot.PermissionModeError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            db.commit()
    db.commit()
    if organising_only:
        session_groups.restore_updated_at(db, session, kept_updated_at)
        db.commit()
    db.refresh(session)
    return _out(db, user, session)


@router.post("/agent/sessions/{session_id}/allowances", response_model=AgentSessionOut)
def add_agent_session_allowance(
    session_id: str, body: SessionAllowance, db: DbSession, user: CurrentUser
) -> AgentSession:
    """「本会话始终允许」加一条(卡上点了它)。在库里那一份上合并 —— 此前界面读出整份、加一条、PATCH 整份,两张卡几乎同时点就丢一条。"""
    session = writable_session(db, user, session_id)
    with autopilot.ALLOWANCE_LOCK:
        try:
            autopilot.add_session_allowance(db, user, session, body.tool, body.permission)
        except autopilot.PermissionModeError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
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
def stream_agent_turn(session_id: str, db: DbSession, user: CurrentUser) -> StreamingResponse:
    """SSE: live token stream of the in-flight turn (snapshots, then done).

    `response_model` 在这里**只为把帧的形状写进 openapi**:返回的是 `StreamingResponse`,
    FastAPI 对直接返回的 Response 不做序列化,所以它不影响流本身。有了它,前端两个消费者
    就从生成类型取形状,不再各写一份 `as {...}` 断言 —— 那两份此前已经不一样了。

    **端点本身是同步的**:查权限要碰库,放在事件循环上做会卡住所有请求(见 api/responses 和那条棘轮);
    流本身是一个异步生成器,照旧在事件循环上一帧一帧发。发之前把会话还掉 —— 这一轮跑多久,流就开多久。
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

    return event_stream(
        db,
        generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.put("/agent/sessions/{session_id}/plan", response_model=AgentSessionOut)
def set_agent_plan(session_id: str, body: AgentPlanUpdate, db: Tx, user: CurrentUser) -> AgentSession:
    """写这次会话的任务计划(见 agent/use_cases.set_plan)。"""
    try:
        return agent_use_cases.set_plan(db, user, session_id, body.steps)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------- 跨会话记忆 ----------
#
# 设置页与智能体共用这组接口:用户在设置里看到的清单,就是每轮注入模型的那一份。
# 两份清单会立刻漂移,而"模型到底记住了什么"是用户唯一想确认的事。


@router.post("/agent/questions", response_model=AgentQuestionOut, status_code=201)
def ask_question(body: AgentQuestionCreate, db: Tx, user: CurrentUser) -> AgentQuestion:
    """智能体问用户一个有选项的问题(闸与归属见 agent/use_cases.ask)。"""
    try:
        return agent_use_cases.ask(db, user, body.session_id, body.questions)
    except agent_questions.QuestionError as exc:
        # 422 而不是 500:这是模型给错了形状,消息里说清怎么改 —— 它下一步就是改了重发。
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/agent/questions/{question_id}", response_model=AgentQuestionOut)
def read_question(question_id: str, db: DbSession, user: CurrentUser) -> AgentQuestion:
    return agent_use_cases.question(db, user, question_id)


@router.get("/agent/questions", response_model=list[AgentQuestionOut])
def list_pending_questions(session_id: str, db: DbSession, user: CurrentUser) -> list[AgentQuestion]:
    return agent_use_cases.pending_questions(db, user, session_id)


@router.post("/agent/questions/{question_id}/answer", response_model=AgentQuestionOut)
def answer_question(question_id: str, body: AgentQuestionAnswer, db: Tx, user: CurrentUser) -> AgentQuestion:
    # 选完要有下文(deliver_to_session):应用自己那条路上模型正停在工具调用里等着,这一送是兜底。
    try:
        return agent_use_cases.answer(db, user, question_id, body.answers)
    except agent_questions.QuestionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/agent/questions/{question_id}/dismiss", response_model=AgentQuestionOut)
def dismiss_question(question_id: str, db: Tx, user: CurrentUser) -> AgentQuestion:
    """不想答。模型会收到「用户跳过了」并继续往下走,而不是卡在那儿等。"""
    return agent_use_cases.dismiss(db, user, question_id)


# ---------- 跨会话记忆 ----------
#
# 设置页与智能体共用这组用例:用户在设置里看到的清单,就是每轮注入模型的那一份。


@router.get("/agent/memories", response_model=list[AgentMemoryOut])
def list_memories(workspace_id: str, db: DbSession, user: CurrentUser, project_id: str = "") -> list:
    return agent_use_cases.list_memories(db, user, workspace_id, project_id or None)


@router.post("/agent/memories", response_model=AgentMemoryOut, status_code=201)
def create_memory(body: AgentMemoryCreate, db: Tx, user: CurrentUser):
    try:
        return agent_use_cases.remember(
            db, user, body.workspace_id, body.content, project_id=body.project_id, source=body.source
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.patch("/agent/memories/{memory_id}", response_model=AgentMemoryOut)
def update_memory(memory_id: str, body: AgentMemoryUpdate, db: Tx, user: CurrentUser):
    try:
        return agent_use_cases.update_memory(db, user, memory_id, body.content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/agent/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: str, db: Tx, user: CurrentUser) -> None:
    agent_use_cases.forget(db, user, memory_id)


@router.get("/agent/toolsets", response_model=list[AgentToolsetOut])
def get_agent_toolsets(db: DbSession, user: CurrentUser) -> list[dict]:
    """给别的智能体看的工具目录(见 domain/agent/toolsets)。清单版本 7 之前叫 /agent/skills。"""
    return list_agent_toolsets(db, user.id)


@router.get("/agent/manifest", response_model=AgentManifestOut)
def get_agent_manifest(db: DbSession, user: CurrentUser) -> AgentManifestOut:
    return AgentManifestOut(
        app="mosael",
        version=app_version(),
        openapi_url="/openapi.json",
        toolsets=[AgentToolsetOut.model_validate(toolset) for toolset in list_agent_toolsets(db, user.id)],
    )


@router.post("/agent/speech")
def speak(body: AgentSpeechRequest, db: Tx, user: CurrentUser) -> Response:
    """念一句话,把音频**直接回给调用方**。

    **不建任务、不入素材库。** 对话里念出来的每一句都登记成素材的话,说十句就是十个音频
    文件 —— 而它们说完就没用了。这和配音是两件事:配音的产出要留存、要进时间线,所以它
    走 job + register_file_asset;这里的产出活到播完为止。

    这条路同时给三件事用:消息底部的播放、确认卡与提问的语音化、失败出声。它们共用同一个
    音色配置(settings/agent-voice),因为对用户来说那就是"它的声音"。

    没设过音色就说没设 —— 不替他挑一个(同 provider-defaults 的立场);「让它出声」关着就不念。
    """
    with tempfile.TemporaryDirectory(prefix="mosael-say-") as tmp, _speech_errors():
        return _audio(agent_use_cases.speak_line(db, user, body.workspace_id, body.text, out_dir=Path(tmp), purpose="chat"))


@router.post("/agent/speech/preview")
def preview_speech(body: AgentSpeechRequest, db: Tx, user: CurrentUser) -> Response:
    """试听设置里存着的那份对话音色。**只要求选好,不要求开着** —— 试听是配置时听一下效果,
    而「先打开才能听」等于让人先对一个没听过的声音点头。

    和 /agent/speech 只差这道闸:合成走同一个 agent_voice.speak,听到的就是以后念给他的那个声音。
    """
    with tempfile.TemporaryDirectory(prefix="mosael-say-") as tmp, _speech_errors():
        return _audio(
            agent_use_cases.speak_line(db, user, body.workspace_id, body.text, out_dir=Path(tmp), purpose="preview")
        )


@router.post("/agent/speech/read")
def read_aloud(body: AgentSpeechRequest, db: Tx, user: CurrentUser) -> Response:
    """用他在「语音对话」里选的那把嗓子念他自己的一段字(笔记选区工具条上的「朗读」),音频直接回给调用方,
    不建任务、不进素材库。

    和试听一样**只要求选好**:「让它出声」管的是对话里它开不开口,不是他想听自己的笔记。没选过就 409 ——
    界面据此退回免费的 Edge 语音,不替他挑一个要花钱的。
    """
    with tempfile.TemporaryDirectory(prefix="mosael-say-") as tmp, _speech_errors():
        return _audio(
            agent_use_cases.speak_line(db, user, body.workspace_id, body.text, out_dir=Path(tmp), purpose="read_aloud")
        )


@contextmanager
def _speech_errors() -> Iterator[None]:
    """两条发声路共用的错误翻译。闸与取配置在 agent/use_cases.speak_line。"""
    from app.domain.voices import agent_voice

    try:
        yield
    except (agent_use_cases.NothingToSay, agent_use_cases.SpeechFailed) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except agent_voice.AgentVoiceUnavailable as exc:
        # 409 而不是 500:这是"还没配好 / 关着",一个用户点两下就能解决的状态。
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _audio(out: Path) -> Response:
    """原样回音频(临时目录删掉之前读出来)。"""
    media_type = "audio/mpeg" if out.suffix == ".mp3" else "audio/wav"
    return Response(content=out.read_bytes(), media_type=media_type, headers={"Cache-Control": "no-store"})


@router.post("/agent/sessions/{session_id}/view")
def set_pending_view(session_id: str, body: AgentPendingView, db: Tx, user: CurrentUser) -> dict[str, str]:
    """智能体要求界面跳到哪儿。**待消费一次**,前端跳完就清。

    方向是反的:智能体跑在后端,而切页面是前端的事。落在会话行上而不是流里 —— 前端本来就在
    轮询会话状态,而免提浮标那种没开 SSE 的场景照样收得到,那恰恰是"带我过去"最有用的时候。
    """
    return {"pending_view": agent_use_cases.set_pending_view(db, user, session_id, body.view, body.id)}


@router.delete("/agent/sessions/{session_id}/view", status_code=204)
def clear_pending_view(session_id: str, db: Tx, user: CurrentUser) -> Response:
    """跳完了。**由前端来清,不是读一次就清** —— 读了就清的话,两个开着的界面里
    只有先读到的那个会跳,而另一个永远不知道发生过什么。

    清它也是写:那是主人的「带我过去」,看共享对话的同事不该替他消费掉(界面上只读会话不跳)。"""
    agent_use_cases.clear_pending_view(db, user, session_id)
    return Response(status_code=204)
