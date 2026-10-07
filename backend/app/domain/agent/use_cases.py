"""智能体会话周边的用例:会话、任务计划、「带我过去」、问用户、跨会话记忆、确认卡的读、念一句话。

闸在这里(见 CONVENTIONS「一次用例一个事务,授权在领域里」):HTTP 路由和智能体工具调同一个函数。
对话的读写闸在 agent/sessions(共享来的对话只能看);开对话、记忆、发声按工作区的 `ai` 权限。不提交事务。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.i18n import LocalizedError
from app.db.models import (
    AgentMemory,
    AgentMessage,
    AgentQuestion,
    AgentSession,
    ProviderProfile,
    ToolConfirmation,
    User,
    now,
)
from app.domain import sharing
from app.domain.agent import host
from app.domain.agent import memory as agent_memory
from app.domain.agent import places
from app.domain.agent import plan as agent_plan
from app.domain.agent import questions as agent_questions
from app.domain.agent.confirmations import decidable_filter
from app.domain.agent.sessions import SHARE_KIND, ensure_reads_for, reads_for_filter, readable_session, writable_session
from app.domain.permissions import NotVisible, ensure_workspace_access, ensure_workspace_perm
from app.domain.voices import agent_voice

#: 会话列表最多给多少条(最近活跃在前)。
SESSION_LIST_LIMIT = 50
#: 确认卡列表一次最多给多少条。
CONFIRMATION_LIST_LIMIT = 100


class UnknownConnection(LocalizedError, ValueError):
    """会话要钉的那条连接不存在,或者不是他的。api 翻成 422。"""


class NothingToSay(LocalizedError, ValueError):
    """要念的是空串。api 翻成 422。"""


class SpeechFailed(LocalizedError, RuntimeError):
    """合成失败 —— 是结果,不是服务端故障。api 翻成 422。"""


# ---------------- 会话 ----------------


def annotate(db: Session, user: User, session: AgentSession) -> AgentSession:
    """标上 `is_mine` / `shared`(界面据 `is_mine` 决定这条对话给不给写,共享来的只能看)和家的名字、状况(按看的人查)。"""
    return annotate_many(db, user, [session], session.workspace_id)[0]


def annotate_many(db: Session, user: User, sessions: list[AgentSession], workspace_id: str) -> list[AgentSession]:
    """一页对话一起标:共享一次查询,家每种地方一次查询。"""
    return places.describe_homes(db, user, sharing.annotate(db, SHARE_KIND, sessions, user, workspace_id))


def checked_profile_id(db: Session, user: User, profile_id: str | None) -> str | None:
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
        raise UnknownConnection("routeErr_aiConnectionNotFound")
    return profile.id


def start_session(
    db: Session,
    user: User,
    workspace_id: str,
    *,
    home: places.Place,
    title: str,
    adapter: str | None = None,
    provider_profile_id: str | None = None,
    model: str | None = None,
) -> AgentSession:
    """开一次对话要 `ai` 权限。对话是**他的** —— 默认不共享给工作区(见 domain/sharing.KINDS)。

    `home`:在哪开的(ADR 0044)。那样东西得在这个工作区里、他看得见(否则 404);ComfyUI 的连接得是他的(否则 422)。
    """
    ensure_workspace_perm(db, user, workspace_id, "ai")
    session = host.create_session(
        db,
        workspace_id=workspace_id,
        home=places.ensure_home(db, user, workspace_id, home),
        title=title,
        adapter=adapter,
        provider_profile_id=checked_profile_id(db, user, provider_profile_id),
        model=model,
    )
    sharing.claim(db, SHARE_KIND, session, user)
    db.flush()
    return annotate(db, user, session)


def list_sessions(db: Session, user: User, workspace_id: str, home: places.Place | None = None) -> list[AgentSession]:
    """最近活跃在前,最多 SESSION_LIST_LIMIT 条。给了 `home` 就只列家在那里的(各处面板的「这里的对话」)。"""
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(AgentSession).where(
        AgentSession.workspace_id == workspace_id,
        AgentSession.origin == "ui",
        sharing.visible_filter(SHARE_KIND, user, workspace_id),
    )
    if home is not None:
        stmt = stmt.where(AgentSession.home_kind == home.kind, AgentSession.home_id == home.id)
    stmt = stmt.order_by(AgentSession.updated_at.desc()).limit(SESSION_LIST_LIMIT)
    return annotate_many(db, user, list(db.scalars(stmt)), workspace_id)


def move_homes(db: Session, user: User, workspace_id: str, kind: str, from_id: str, to_id: str) -> int:
    """家跟着挪(ADR 0044 §9):只有 ComfyUI 的 —— Mosael 自家的东西按 id 认,永远不用挪。只挪他自己的对话。"""
    ensure_workspace_perm(db, user, workspace_id, "ai")
    if kind != places.COMFYUI:
        raise places.PlaceError("agentErr_placeOnlyComfyMoves")
    return places.move_comfy_homes(db, user, workspace_id, from_id, to_id)


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
    #: 什么时候要求的:过了 30 秒前端不跟(ADR 0044 §6)。
    session.pending_view_at = now()
    return session.pending_view


def clear_pending_view(db: Session, user: User, session_id: str) -> None:
    """跳完了。清它也是写:那是主人的「带我过去」,看共享对话的同事不该替他消费掉。"""
    session = writable_session(db, user, session_id)
    session.pending_view = ""
    session.pending_view_at = None


def cited_message(db: Session, user: User, workspace_id: str, message_id: str) -> tuple[AgentMessage, str]:
    """笔记引用的一条对话消息。得看得见它所在的那次对话:笔记是工作区的,引用的对话却可能是某人没共享的
    私人线程 —— 引用它不等于把它公开。看不见和不存在同一个回答。

    放在智能体这边而不是笔记那边:它问的是「这次对话你看不看得见」,笔记域认识了会话就和智能体成环。
    """
    ensure_workspace_access(db, user, workspace_id)
    message = db.get(AgentMessage, message_id)
    try:
        session = readable_session(db, user, message.session_id) if message else None
    except NotVisible:
        session = None
    if message is None or session is None or session.workspace_id != workspace_id:
        raise NotVisible("routeErr_noteSourceNotFound")
    return message, session.id


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


# ---------------- 确认卡(读) ----------------
#
# 一张卡跟着发起它的那次对话走:别人没共享的对话里的卡(工具名、参数)他看不到,和那次对话本身一样
# (判据在 agent/sessions.reads_for_filter)。批 / 拒的闸在 agent/confirmations.authorize_and_*。


def list_confirmations(
    db: Session,
    user: User,
    workspace_id: str,
    *,
    status: str | None = None,
    limit: int = 30,
    session_id: str | None = None,
    unowned: bool = False,
    decidable: bool = False,
    automatic: bool = False,
) -> list[ToolConfirmation]:
    ensure_workspace_access(db, user, workspace_id)
    stmt = select(ToolConfirmation).where(
        ToolConfirmation.workspace_id == workspace_id,
        reads_for_filter(ToolConfirmation.session_id, user.id, workspace_id),
    )
    if session_id:
        ensure_reads_for(db, session_id, user.id)
        stmt = stmt.where(ToolConfirmation.session_id == session_id)
    elif unowned:
        stmt = stmt.where(ToolConfirmation.session_id.is_(None))
    if decidable:
        stmt = stmt.where(decidable_filter(db, user, workspace_id))
    if automatic:
        # 自动放行在派活之前就把 decision_mode 改掉了;退回给人的那条路会改回 manual(见 autopilot)。
        stmt = stmt.where(ToolConfirmation.decision_mode != "manual")
    if status:
        stmt = stmt.where(ToolConfirmation.status == status)
    if status == "pending":
        # 隔离判断者正在看的卡先不显示:它几秒内多半会自己消失(放行了),让用户看见一张自己出现
        # 又自己消失的卡只会造成困惑。期限一过它自动回到这里 —— 不需要任何回收动作。
        stmt = stmt.where(or_(ToolConfirmation.hold_until.is_(None), ToolConfirmation.hold_until <= now()))
    stmt = stmt.order_by(ToolConfirmation.created_at.desc()).limit(min(limit, CONFIRMATION_LIST_LIMIT))
    return list(db.scalars(stmt))


def confirmation(db: Session, user: User, confirmation_id: str) -> ToolConfirmation:
    """他看得见的那一张:工作区的人,且看得见卡挂着的那次对话。看不见和不存在同一个回答。"""
    row = db.get(ToolConfirmation, confirmation_id)
    if row is None:
        raise NotVisible("Not found")
    ensure_workspace_access(db, user, row.workspace_id)
    ensure_reads_for(db, row.session_id, user.id)
    return row


# ---------------- 念一句话 ----------------


#: 用他选的那把嗓子念,是为了什么 → (取配置的那道闸, 记账来源)。
#:
#: - chat:对话里它说话 —— 要「让它出声」开着;
#: - preview:设置页试听 —— 只要选好(试听发生在打开之前);
#: - read_aloud:笔记选区工具条上的「朗读」,念的是他自己的字 —— 只要选好(「让它出声」管的是对话里它开不开口)。
#:
#: 三样都花钱、都记账(各家 TTS 按字符计费),来源分开写,统计里才看得出钱花在哪儿。
SPEECH_PURPOSES = {
    "chat": (agent_voice.require_enabled, "agent_speech"),
    "preview": (agent_voice.require_ready, "agent_voice_preview"),
    "read_aloud": (agent_voice.require_ready, "note_read_aloud"),
}


def speak_line(db: Session, user: User, workspace_id: str, text: str, *, out_dir: Path, purpose: str) -> Path:
    """用他选的那把嗓子(设置「语音对话」)念一段,落到 `out_dir`。为了什么念见 SPEECH_PURPOSES。

    念一句是**花钱的**(各家 TTS 按字符计费),所以要 `ai` 权限,和对话、生成同一档。
    """
    gate, source_type = SPEECH_PURPOSES[purpose]
    ensure_workspace_perm(db, user, workspace_id, "ai")
    text = text.strip()
    if not text:
        raise NothingToSay("routeErr_nothingToRead")
    pref = gate(db, user.id)
    from app.domain.voices.remote import RemoteConsentRequired

    try:
        return agent_voice.speak(
            db,
            pref,
            text=text,
            workspace_id=workspace_id,
            out_dir=out_dir,
            source_type=source_type,
        )
    except RemoteConsentRequired:
        raise  # 不是失败:这个账号还没同意上传这把嗓子,界面据它弹确认框(ADR 0037)
    except Exception as exc:  # noqa: BLE001 — 合成失败是结果,不是服务端故障
        raise SpeechFailed(str(exc)[:300]) from exc
