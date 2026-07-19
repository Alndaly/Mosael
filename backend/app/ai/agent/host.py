from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agent.adapters import AdapterError, TurnResult, run_turn
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import new_session_token
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
    _stream_reset(session_id)
    final_text = ""
    turn_started = time.monotonic()
    with SessionLocal() as db:
        session = db.get(AgentSession, session_id)
        if session is None:
            return
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
                agent_model = model or profile.default_model
        try:
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
            )
            final_text = result.text
            if result.adapter_state is not None:
                session.adapter_state = result.adapter_state  # pi 多轮记忆:回存序列化消息
            tool_cards = get_stream_state(session_id)["tools"]  # 持久化工具卡到消息,turn 结束后仍可见
            db.add(
                AgentMessage(
                    session_id=session.id,
                    role="assistant",
                    content=result.text,
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
            db.commit()
            _stream_finish(session_id, final_text)
    for callback in list(_turn_callbacks):
        try:
            callback(session_id)
        except Exception:
            logger.exception("Turn callback failed")
