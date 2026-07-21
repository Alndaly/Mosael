from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agent.adapters import AdapterError, TurnResult, abort_turn, run_turn, set_turn_queue, steer_turn
from app.ai.agent.textclean import decode_byte_fallback
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.db.models import AgentMessage, AgentSession, AuthSession, User, now
from app.domain.agent.prompt_skills import skills_index_for_prompt

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
- 用 analyze_asset 理解图片/视频素材的内容(用户消息里的 [附件 asset_id=…] 就是刚上传的素材)。
- 知识库(用户的脚本/文案/风格指南/资料)用 search_kb 检索、read_kb_document 读全文;
  写文案或规划剪辑前先查知识库。用户要求保存的成稿用 create_kb_note 存入。
- 需要联网查最新资料时用 web_search 搜索、fetch_url 读网页(只读,随时可用)。
- 所有已批准的时间线修改用户都可以撤销,不必过度谨慎,但一次确认卡只装一个连贯意图。
工作区 ID: {workspace_id}。用用户使用的语言回复,简洁、面向创作者,不要提及内部实现细节。
不要读写本机文件系统,不要执行 shell 命令;只使用 mibu 工具与对话。

你有一组技能(可复用的操作手册)。当任务命中某个技能时,先用 load_skill 拉取正文,
再严格按其流程执行;不确定时也可先 list_skills 查看。当前技能索引:
{skills_index}"""

_turn_callbacks: list[Callable[[str], None]] = []

# Live token streams for in-flight turns, keyed by session id.
_streams_lock = threading.Lock()
_streams: dict[str, dict] = {}


def get_stream_state(session_id: str) -> dict:
    with _streams_lock:
        state = _streams.get(session_id)
        if not state:
            return {"text": "", "done": True, "seq": 0, "tools": []}
        snapshot = dict(state)
        snapshot["tools"] = [dict(card) for card in state["tools"]]
        return snapshot


def _stream_reset(session_id: str) -> None:
    with _streams_lock:
        _streams[session_id] = {"text": "", "done": False, "seq": 0, "tools": []}


def _stream_tool_event(session_id: str, event: dict) -> None:
    """pi 工具事件 → 流里的工具卡:tool_start 建卡(running),tool_end 更新(done/error)。"""
    with _streams_lock:
        state = _streams.get(session_id)
        if state is None:
            return
        cards: list[dict] = state["tools"]
        if event.get("type") == "tool_start":
            cards.append(
                {"id": event.get("toolCallId"), "name": event.get("name"), "args": event.get("args"), "status": "running"}
            )
        elif event.get("type") == "tool_end":
            for card in cards:
                if card["id"] == event.get("toolCallId"):
                    card["status"] = "error" if event.get("isError") else "done"
                    card["result"] = event.get("result")
                    break
        state["seq"] += 1


def _stream_append(session_id: str, delta: str) -> None:
    with _streams_lock:
        state = _streams.get(session_id)
        if state is not None:
            state["text"] += delta
            state["seq"] += 1


def _stream_finish(session_id: str, final_text: str) -> None:
    with _streams_lock:
        state = _streams.setdefault(session_id, {"text": "", "done": False, "seq": 0, "tools": []})
        state["text"] = final_text
        state["done"] = True
        state["seq"] += 1


def on_turn_finished(callback: Callable[[str], None]) -> None:
    """Register a listener (e.g. the Feishu worker) fired with session_id after each turn."""
    _turn_callbacks.append(callback)


def default_adapter() -> str:
    """The CLI backing the agent — `pi` is the standard. MIBU_AGENT_CLI can override it
    (e.g. `claude`) for machines where that's what's installed."""
    return os.environ.get("MIBU_AGENT_CLI", "pi")


def create_session(
    db: Session,
    *,
    workspace_id: str,
    project_id: str | None = None,
    origin: str = "ui",
    external_key: str | None = None,
    title: str = "新对话",
    adapter: str | None = None,
    provider_profile_id: str | None = None,
    model: str | None = None,
) -> AgentSession:
    session = AgentSession(
        workspace_id=workspace_id,
        project_id=project_id,
        origin=origin,
        external_key=external_key,
        title=title,
        adapter=adapter or default_adapter(),
        provider_profile_id=provider_profile_id,
        model=model or None,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def append_message(
    db: Session, session_id: str, *, role: str, content: str, error: str | None = None
) -> AgentMessage:
    """往会话里追加一条消息(不 commit,跟随调用方事务)。

    AgentMessage 行只在 agent 归属方创建(ownership.py)——飞书等集成经这里写,
    不直接构造模型。"""
    message = AgentMessage(session_id=session_id, role=role, content=content, error=error)
    db.add(message)
    return message


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
        # Queued, not steered. These are two different things and only one of them should be
        # the default: queuing waits for the whole reason-act loop to finish and then runs as
        # its own turn, which is what someone typing a follow-up almost always means. Steering
        # cuts into the running loop, changing what the agent does next — powerful, and wrong
        # to apply to every message someone happens to send early. It is opt-in per message
        # (steer_queued_message) the way Codex offers it as an action on the pending item.
        # The sender rides along: a queued turn is run later by a background thread, which has
        # no request and therefore no user to mint a service token for. The session does not
        # record an owner, so the message has to.
        message = AgentMessage(
            session_id=session.id,
            role="user",
            content=content,
            payload={"queued": True, "queued_by": user.id},
        )
        db.add(message)
        db.commit()
        db.refresh(message)
        return message
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


def mint_tool_token(db: Session, user: User) -> str:
    """Public alias — the agent-tools endpoint needs the same short-lived credential a turn gets."""
    return _mint_service_token(db, user)


def _mint_service_token(db: Session, user: User) -> str:
    return mint_service_session(db, user.id)


def _run_turn_thread(session_id: str, prompt: str, token: str) -> None:
    api_base = f"http://{settings.backend_host}:{settings.backend_port}"
    _stream_reset(session_id)
    final_text = ""
    turn_started = time.monotonic()
    with SessionLocal() as db:
        session = db.get(AgentSession, session_id)
        if session is None:
            return
        # Everything below runs inside the try: a failure while resolving the provider (or
        # building the prompt) must still write an error message and reset session.status —
        # otherwise the worker dies silently and the session hangs in "running" forever.
        try:
            system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
                workspace_id=session.workspace_id,
                skills_index=skills_index_for_prompt() or "(暂无技能)",
            )
            # pi 适配器的对话模型:优先用会话选定的供应商+模型,否则回退第一个启用供应商及其默认模型
            provider_dict: dict | None = None
            agent_model: str | None = None
            if session.adapter == "pi":
                from app.domain.provider_defaults import resolve_default
                from app.domain.providers import first_enabled_profile, resolve_profile

                # 解析顺序:会话选定 → 「对话」能力的默认供应商 → 第一个启用供应商
                profile = None
                model = session.model or ""
                if session.provider_profile_id:
                    profile = resolve_profile(db, "", session.provider_profile_id)
                if profile is None:
                    default_profile, default_model = resolve_default(db, "chat")
                    if default_profile is not None:
                        profile = default_profile
                        model = model or default_model
                if profile is None:
                    profile = first_enabled_profile(db)
                if profile is not None:
                    provider_dict = {"base_url": profile.base_url, "api_key": profile.api_key, "vendor": profile.vendor}
                    agent_model = (model or profile.default_model or "").strip()
                    # A profile with no usable model would otherwise reach the sidecar as model=""
                    # and come back as a silent empty turn.
                    if not agent_model:
                        raise AdapterError(
                            f"供应商「{profile.name}」没有可用的模型:请在设置里为它填写默认模型,"
                            "或在对话框的模型选择器里选一个。"
                        )
            result: TurnResult = run_turn(
                session.adapter,
                prompt=prompt,
                system_prompt=system_prompt,
                api_base=api_base,
                token=token,
                adapter_session_id=session.adapter_session_id,
                on_delta=lambda delta: _stream_append(session_id, delta),
                on_tool=lambda event: _stream_tool_event(session_id, event),
                provider=provider_dict,
                model=agent_model,
                workspace_id=session.workspace_id,
                adapter_state=session.adapter_state,
                session_key=session.id,
            )
            # 本地模型的 byte-fallback token(<0xF0>… 字面串)在落库前重组回 UTF-8。
            final_text = decode_byte_fallback(result.text)
            if result.adapter_state is not None:
                session.adapter_state = result.adapter_state  # pi 多轮记忆:回存序列化消息
            tool_cards = get_stream_state(session_id)["tools"]  # 持久化工具卡到消息,turn 结束后仍可见
            # Never persist a blank assistant turn: an empty reply with no tool calls means the
            # model call failed somewhere upstream. Surfacing it as an empty bubble is what made
            # provider misconfiguration look like "nothing happened".
            if not final_text.strip() and not tool_cards:
                raise AdapterError(
                    "模型没有返回任何内容。请检查 AI 供应商配置:base_url 是否完整"
                    "(含端口与 /v1,如 http://localhost:11434/v1)、模型名是否存在、服务是否可达。"
                )
            db.add(
                AgentMessage(
                    session_id=session.id,
                    role="assistant",
                    content=final_text,
                    payload={
                        "duration_seconds": round(time.monotonic() - turn_started, 1),
                        **({"tools": tool_cards} if tool_cards else {}),
                    },
                )
            )
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
            # Revoke the service token this turn was given. It is minted per turn so the MCP
            # server can call back into the API, and nothing ever removed it — AuthSession has
            # no expiry, so every chat turn left a permanent full-privilege credential in the
            # database. A long-running install accumulated one per message, forever.
            service_session = db.get(AuthSession, token)
            if service_session is not None:
                db.delete(service_session)
            try:
                db.commit()
            except Exception:  # noqa: BLE001
                # The session can be deleted while its turn is still running. There is then no
                # row to mark idle, and letting this propagate kills the thread before
                # _stream_finish — leaving the UI spinning on a conversation that is gone.
                logger.warning("Could not finalise session %s; it may have been deleted", session_id)
                db.rollback()
            _stream_finish(session_id, final_text)
    for callback in list(_turn_callbacks):
        try:
            callback(session_id)
        except Exception:
            logger.exception("Turn callback failed")
    # Outside the session block on purpose: the drain opens its own session and starts the
    # next turn, and doing that while this one still held the connection would nest them.
    _drain_queue(session_id)


def _drain_queue(session_id: str) -> None:
    """Run the next queued message, if any, as its own turn.

    This is what makes the default behaviour a queue rather than a hint: the message waits for
    the whole reason-act loop to finish and then gets a turn of its own, answered on its own
    terms instead of merged into someone else's answer.
    """
    try:
        _drain_queue_locked(session_id)
    except Exception:  # noqa: BLE001 — a background drain must not take the process with it
        # The session can be deleted while its turn is still finishing, and the queue is then
        # meaningless. Anything else here is a real fault worth a traceback in the log.
        logger.exception("Draining the queue for session %s failed", session_id)


def _drain_queue_locked(session_id: str) -> None:
    with SessionLocal() as db:
        session = db.get(AgentSession, session_id)
        if session is None or session.status == "running":
            return
        pending = _queued_messages(db, session)
        if not pending:
            return
        message = pending[0]
        owner_id = (message.payload or {}).get("queued_by")
        owner = db.get(User, owner_id) if owner_id else None
        _unqueue(db, message)
        if owner is None:
            # Without a sender there is no credential to run as. Clearing the flag anyway so it
            # is not retried on every subsequent turn — a message that silently reappears
            # forever is worse than one that visibly did not run.
            logger.warning("queued message %s has no sender; not running it", message.id)
            db.commit()
            return
        session.status = "running"
        db.commit()
        token = _mint_service_token(db, owner)
        content = message.content
    threading.Thread(target=_run_turn_thread, args=(session_id, content, token), daemon=True).start()


def cancel_queued_message(db: Session, session: AgentSession, message_id: str) -> list[str]:
    """Drop a message that has not run yet."""
    message = db.get(AgentMessage, message_id)
    if message is None or message.session_id != session.id or not (message.payload or {}).get("queued"):
        raise HostError("这条消息已经开始处理,无法撤回")
    db.delete(message)
    db.commit()
    return [item.content for item in _queued_messages(db, session)]


def _queued_messages(db: Session, session: AgentSession) -> list[AgentMessage]:
    """Messages waiting to be run, oldest first.

    Marked explicitly rather than inferred from position: once a message is steered into the
    running turn it is no longer queued, and no amount of looking at where it sits in the
    transcript can tell you that.
    """
    messages = db.scalars(
        select(AgentMessage)
        .where(AgentMessage.session_id == session.id, AgentMessage.role == "user")
        .order_by(AgentMessage.created_at)
    )
    return [message for message in messages if (message.payload or {}).get("queued")]


def _unqueue(db: Session, message: AgentMessage) -> None:
    """Take a message out of the queue, as of now.

    The timestamp is restamped on purpose. The transcript is ordered by created_at, and a
    queued message was stamped when it was typed — long before it was sent. Left alone it
    sorts ahead of the answer to the previous turn, so a conversation reads as every question
    in a row followed by every answer in a row. It enters the conversation when it is
    dequeued, and that is the time the transcript should show.

    Assigning a new dict matters too — mutating the JSON column in place leaves SQLAlchemy
    seeing no change and the write silently does nothing.
    """
    payload = dict(message.payload or {})
    payload.pop("queued", None)
    payload.pop("queued_by", None)
    message.payload = payload
    message.created_at = now()


def steer_queued_message(db: Session, session: AgentSession, message_id: str, user: User) -> bool:
    """Cut a queued message into the running turn instead of waiting for it.

    Returns False when there was no live turn to cut into — the message stays queued and will
    run on its own, which is a better outcome than reporting a failure the user cannot act on.
    """
    message = db.get(AgentMessage, message_id)
    if message is None or message.session_id != session.id or not (message.payload or {}).get("queued"):
        raise HostError("找不到这条排队消息")
    if not steer_turn(session.id, message.content):
        return False
    _unqueue(db, message)
    db.commit()
    return True


def queued_messages(db: Session, session: AgentSession) -> list[AgentMessage]:
    """Public view of what is still waiting behind the current answer."""
    return _queued_messages(db, session)


def stop_turn(db: Session, session: AgentSession) -> bool:
    """Stop the running turn. Whatever it already produced is kept and persisted.

    Returns False when nothing was running — a stop button the user pressed a moment too late
    is not an error, and reporting one would be noise.
    """
    if session.status != "running":
        return False
    return abort_turn(session.id)
