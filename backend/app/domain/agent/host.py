from __future__ import annotations

import json
import logging
import math
import threading
import time

from sqlalchemy import and_, exists, or_, select, update
from sqlalchemy.orm import Session

from app.ai.sidecar.pi_client import SidecarError, TurnResult, abort_turn, compact_session, run_turn, steer_turn
from app.domain.agent.prompt import (
    _attached_images,
    _prompt_snapshot,
    _prompt_with_context,
    build_system_prompt,
    job_receipts_prompt,
    origin_marker_for,
    session_title,
    user_prompt,
    with_origin_envelope,
)
from app.domain.agent.stream import (
    get_stream_state,
    _stream_append,
    _stream_finish,
    _stream_reset,
    _stream_thinking,
    _stream_tool_event,
    _timeline_for_payload,
)
from app.domain.agent import origins
from app.domain.agent.textclean import decode_byte_fallback
from app.domain.providers import models as provider_models
from app.domain.providers.runtime import sidecar_provider
from app.domain.context_meter import CHARS_PER_TOKEN, context_breakdown, context_tokens
from app.domain.providers.model_limits import fallback_context_window
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.i18n import LocalizedError, get_current_locale, set_current_locale, tr
from app.core.security import mint_service_session, revoke_session
from app.db.models import AgentMessage, AgentSession, ToolConfirmation, User, now
from app.core.token_estimate import estimate_text_tokens
from app.domain.billing.usage import billable

"""
Agent host (plan §16 + user decision): sessions and messages live in Mosael;
each turn drives a specialized external agent CLI whose only write path into
Mosael is the MCP tool surface guarded by confirmation cards.
"""

logger = logging.getLogger(__name__)


# Live token streams for in-flight turns, keyed by session id.

#: Turn threads carry this name so callers can find and drain them.
#: A turn runs in a daemon thread that keeps writing to the DB after the request that started it
#: returned. That is fine in production — the process outlives the turn. It is NOT fine for a test
#: harness that drops and recreates the schema between tests: a leftover turn then writes into a
#: half-rebuilt database, which surfaces as a FOREIGN KEY failure inside the turn, a stale-schema
#: `duplicate column` during migration, or another test's message appearing in this test's list.
#: See `wait_for_idle_turns` and its use in tests/util.fresh_client.
TURN_THREAD_NAME = "agent-turn"

def wait_for_idle_turns(timeout: float = 5.0) -> bool:
    """Block until no agent turn thread is running. Returns False if `timeout` ran out.

    Exists for the test harness, which must not tear the schema down under a live turn. Production
    never needs it — nothing there rebuilds the database mid-flight.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        alive = [t for t in threading.enumerate() if t.name == TURN_THREAD_NAME and t.is_alive()]
        if not alive:
            return True
        alive[0].join(timeout=max(0.0, deadline - time.monotonic()))
    return not any(t.name == TURN_THREAD_NAME and t.is_alive() for t in threading.enumerate())


def resolve_chat_provider(
    db: Session, provider_profile_id: str | None, model: str, *, user_id: str | None
) -> tuple[dict | None, str | None, object | None]:
    """pi 适配器的供应商三级解析:会话选定 → 「对话」能力默认 → 第一个启用供应商。
    AI Studio 与飞书共用 — 飞书早先裸调 run_turn 不带 provider,配好了供应商也
    永远报「未配置」,就是漏了这一步。返回 (provider_dict, model, profile)。"""
    from app.domain.providers.selection import resolve_connection

    from app.domain.providers import credentials as provider_credentials

    profile = None
    if provider_profile_id:
        profile = resolve_connection(db, "", provider_profile_id, user_id=user_id)
    if profile is None:
        # 默认解析已经是模型粒度的:拿到的是一行模型,连接就在它身上。
        default = provider_models.resolve_default(db, "chat", user_id)
        if default is not None:
            profile = provider_credentials.resolve_connection(db, default.profile, user_id)
            model = model or default.model_id
    if profile is None:
        # **不再回退到"第一个启用的连接"。** 那个兜底的失败方式跑出来过:界面显示 DeepSeek、
        # 回答却是「我是 Kimi」—— 碰巧第一个是订阅计划连接,而订阅走它自己的 provider 定义
        # (自带身份、自带思考)。没有默认就说没有,这句话用户看得懂;悄悄换一个他看不懂。
        raise SidecarError(tr("agentErr_noChatModelChosen"))
    if not (model or "").strip():
        # 没指定模型时用这条连接下第一个能对话的模型。default_model 那个字段正在退场 ——
        # 它是"一档案一模型"时代的写法,同一条连接有多个对话模型时它给不出答案。
        for candidate in provider_models.list_models(db, profile.id, enabled_only=True):
            if "chat" in provider_models.effective_capabilities(candidate):
                model = candidate.model_id
                break
    agent_model = (model or provider_models.model_id_for(db, profile, "chat")).strip()
    # A profile with no usable model would otherwise reach the sidecar as model=""
    # and come back as a silent empty turn.
    if not agent_model:
        raise SidecarError(tr("agentErr_connectionNoModel", name=profile.name))
    provider_dict = sidecar_provider(db, profile, agent_model)
    return provider_dict, agent_model, profile





















def _usage_from_started(started: float, first_token_at: float | None = None) -> dict:
    """这一轮的耗时。**测不到的不写进去** —— 缺键和 0 是两回事,前端据此显示「—」而不是「0.0s」。"""
    usage = {"duration_seconds": round(max(0.0, time.monotonic() - started), 1)}
    if isinstance(first_token_at, (int, float)):
        # 从轮开始算起,而不是从请求发出算起:准备提示词、装配上下文的时间,用户也在等。
        usage["first_token_seconds"] = round(max(0.0, first_token_at - started), 2)
    return usage


def _turn_metering(prompt: str, text: str, adapter_usage: dict | None = None) -> dict:
    metering = dict(adapter_usage or {})
    metering.setdefault("requests", 1)
    metering.setdefault("input_characters", len(prompt))
    metering.setdefault("output_characters", len(text))
    has_token_usage = any(
        key in metering
        for key in (
            "token",
            "tokens",
            "total_token",
            "total_tokens",
            "input_token",
            "input_tokens",
            "prompt_tokens",
            "output_token",
            "output_tokens",
            "completion_tokens",
        )
    )
    if not has_token_usage:
        input_tokens = estimate_text_tokens(prompt)
        output_tokens = estimate_text_tokens(text)
        metering["input_tokens"] = input_tokens
        metering["output_tokens"] = output_tokens
        metering["total_tokens"] = input_tokens + output_tokens
        metering["token_estimate"] = True
    return metering


def default_adapter() -> str:
    """智能体运行时。目前只有 pi(agent-sidecar 里嵌 pi-agent-core)。

    这里保留一层间接:会话表记着自己是被哪个运行时跑的,换运行时时旧会话仍能被正确解读。
    曾经还有一条「把 Claude Code CLI 当后端」的路(--mcp-config 起子进程),因为长期没人走、
    且缺少会话归属与工具回调而删除。
    """
    return "pi"


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


def get_or_create_external_session(
    db: Session, *, workspace_id: str, origin: str, external_key: str, title: str
) -> AgentSession:
    """外部入口(飞书的一个会话、一个工作流)各自那条长期会话:按 external_key 找回,没有就建。
    `origin` 说是从哪来的 —— 飞书会话不给 bypass 之类的规则按它判(见 autopilot.set_permission_mode)。"""
    existing = db.scalar(select(AgentSession).where(AgentSession.external_key == external_key))
    if existing is not None:
        return existing
    return create_session(db, workspace_id=workspace_id, origin=origin, external_key=external_key, title=title)


class HostError(LocalizedError, RuntimeError):
    """排队消息之类的请求做不了。带文案 key(`agentErr_*`),按请求方的语言翻。"""


def unseen_since_last_success(db: Session, session: AgentSession) -> str:
    """失败的那几轮,模型其实从来没见过 —— 把它们如实补给它。

    模型的记忆是 `session.adapter_state`(pi 序列化的消息),而**只有成功的回合会回存它**
    (见下面那两条 except:它们写 AgentMessage、记账、标失败,唯独不碰 adapter_state)。
    于是一失败,界面上的对话和模型的对话就分叉:用户看得见自己说过的话和那条「执行失败」,
    模型两样都没有,它的记忆停在最后一次成功的回合。

    真机上的样子是:用户说「再试一次」,模型答「这句含义不太明确」,然后照着**上一次成功**
    那轮的话题往下推。它不是在装傻 —— 它确实不知道中间试过什么、又为什么没成。

    这里不替它重放那次请求(那是用户的决定,不是我们的),只把丢掉的那一段说清楚:
    当时说了什么、失败在哪。没有失败就返回空串,一个字都不加。
    """
    last_ok = db.scalar(
        select(AgentMessage.created_at)
        .where(
            AgentMessage.session_id == session.id,
            AgentMessage.role == "assistant",
            AgentMessage.error.is_(None),
        )
        .order_by(AgentMessage.created_at.desc())
        .limit(1)
    )
    stmt = select(AgentMessage).where(
        AgentMessage.session_id == session.id,
        AgentMessage.role.in_(("user", "assistant")),
    )
    if last_ok is not None:
        stmt = stmt.where(AgentMessage.created_at > last_ok)
    rows = list(db.scalars(stmt.order_by(AgentMessage.created_at)).all())
    if not any(row.error for row in rows):
        return ""
    lines: list[str] = []
    for row in rows:
        if row.role == "user":
            lines.append(f"· 用户说:{(row.content or '').strip()[:300]}")
        elif row.error:
            lines.append(f"· 那一轮失败了:{row.error.strip()[:300]}")
    return (
        "【上面这些你没有见过】下面几轮因为执行失败,没有进入你的对话记忆 —— "
        "它们在用户的界面上是可见的,所以他会以为你知道:\n"
        + "\n".join(lines)
        + "\n如果这次的消息是在指代它们(比如「再试一次」),按这段来理解;不要说你不明白他在说什么。"
    )




#: 引用清单里每一类叫什么、该用哪个工具去读。**说出工具名**是有意的:只给 id 的话,
#: 模型得先猜"笔记要用哪个工具",而猜错一次就是一轮白跑。


#: 每一类去哪张表里找。用来核对"这个 id 现在还在不在、在不在这个工作区里"。










#: 一条消息**从哪儿来**。key 是落在 payload 里的标记名,值是给模型看的那句信封。
#:
#: 摊成一张表是因为信封此前在两个地方各拼了一遍(直发一处、排队一处):加第二种来源时,
#: 漏改的那一处不会报错 —— 模型只是收到一条没头没尾的消息,不知道是谁说的。






#: 后台任务的回执落库用的角色。**它不是用户消息**:此前回执借用户的名义进会话(role=user + from_job),
#: 会话正忙时就带着 queued 进了排队 —— 输入框上方排出七八条「「配音 3」已完成」,带着 Steer 和删除,
#: 这一轮结束后又每条各跑一轮(用户截图)。现在它有自己的角色:不进队列,界面画成一行任务通知。
#:
#: payload:`job_id`(哪个任务);还没交给智能体的另带 `undelivered: true` 和 `deliver_as`(以谁的身份跑
#: 那一轮 —— 建任务的人,和排队消息的 queued_by 同一个理由:后台线程没有请求可以认人)。
JOB_RECEIPT_ROLE = "job_receipt"


def _waiting(session_id: str):
    """「这个会话有东西在等下一轮」的条件:有人排了话,或者有回执还没交给智能体。"""
    return exists().where(
        AgentMessage.session_id == session_id,
        or_(
            and_(AgentMessage.role == "user", AgentMessage.payload["queued"].as_boolean().is_(True)),
            and_(AgentMessage.role == JOB_RECEIPT_ROLE, AgentMessage.payload["undelivered"].as_boolean().is_(True)),
        ),
    )


def _claim_idle_session(db: Session, session_id: str, *, only_if_queued: bool = False) -> bool:
    """Atomically reserve the session for exactly one direct sender or queue drain.

    Reading ``session.status`` and assigning it later is not a claim: another request can start a
    turn in that gap. Keep the conditional update in one shared primitive so the direct-message
    and drain paths cannot drift back to different locking rules.

    ``only_if_queued``(队列 drain 用):**有东西在等才抢**(排队的话、没送的回执),和「是不是空闲」写在
    同一条条件更新里。此前 drain 是先抢(置 running 并提交)、再看队列、空的再放回 idle —— 每一轮结束后
    都有一小段「没有任何一轮在跑,会话却显示 running」:界面上闪一下「思考中」,CI 里
    test_turn_error_becomes_assistant_error_message 时不时正好读到这一刻。先看队列再抢也不行,
    那正是两个 drain 抢同一条消息的缝;两个条件交给数据库一步裁决,缝就没了。
    """
    claim = update(AgentSession).where(AgentSession.id == session_id, AgentSession.status != "running")
    if only_if_queued:
        claim = claim.where(_waiting(session_id))
    return bool(db.execute(claim.values(status="running")).rowcount)


def _undelivered_receipts(db: Session, session: AgentSession) -> list[AgentMessage]:
    """还没交给智能体的回执,按到达先后。"""
    rows = db.scalars(
        select(AgentMessage)
        .where(AgentMessage.session_id == session.id, AgentMessage.role == JOB_RECEIPT_ROLE)
        .order_by(AgentMessage.created_at)
    )
    return [row for row in rows if (row.payload or {}).get("undelivered")]


def _hand_over_receipts(db: Session, session: AgentSession, *, before_user: bool) -> str:
    """把还没送的回执**一次**交出去:标成已送、时间戳改成现在,返回给模型的那一段(没有就是空串)。

    时间戳改成交出去的这一刻,和 `_unqueue` 同一个理由:对话按 created_at 排,回执落库时那一轮还在跑,
    它的回答要到这一轮结束才落库 —— 不改的话回执排在那个回答**前面**,读起来像回答之前就收到了。
    界面在这期间把它们画在正在跑的那一轮下面(见前端 CanvasAgentChat / ChatWorkspace),交出去之后
    的位置和那时一致。
    """
    receipts = _undelivered_receipts(db, session)
    for receipt in receipts:
        payload = dict(receipt.payload or {})
        payload.pop("undelivered", None)
        payload.pop("deliver_as", None)
        receipt.payload = payload
        receipt.created_at = now()
    return job_receipts_prompt(
        [(str((receipt.payload or {}).get("job_id") or ""), receipt.content) for receipt in receipts],
        before_user=before_user,
    )


def _with_receipts(prompt: str, receipts: str) -> str:
    return f"{receipts}\n\n{prompt}" if receipts else prompt


def post_job_receipt(db: Session, session: AgentSession, content: str, owner: User, *, job_id: str) -> AgentMessage:
    """一个后台任务跑完了,把回执交给这次对话的智能体。

    **会话空闲**:回执落库(已送),直接起一轮,那一轮的提示词就是这条回执(连同此前没送出去的,如果有)。
    **会话正忙**:回执落库成「待送」,**不进队列** —— 这一轮结束时 drain 把攒下的回执合成一次交出去:
    只有回执就起一轮;有人排了话,就搭那一轮的车(见 _drain_queue_locked)。

    为什么不插进正在跑的这一轮(steer / follow_up):pi 的插话队列在「最后一次取队列之后、这一轮收尾之前」有一道缝,
    落进缝里的消息就丢了(agent-sidecar/src/subagent.ts 为同一个缝选了收尾清算);而回执丢了,智能体就永远不知道
    那个任务跑完了。收尾时从库里取没有这道缝,代价是晚到这一轮结束 —— 而这一轮本来也在忙别的。
    """
    if _claim_idle_session(db, session.id):
        # 失败的那几轮模型没见过(失败不回存 adapter_state),而用户以为它见过 —— 和用户消息同一处补法。
        unseen = unseen_since_last_success(db, session)
        # 先交出此前没送出去的(如果有),这一条排在它们后面 —— 同一轮里一并交给智能体。
        earlier = _hand_over_receipts(db, session, before_user=False)
        prompt = _with_receipts(job_receipts_prompt([(job_id, content)], before_user=False), earlier)
        message = AgentMessage(session_id=session.id, role=JOB_RECEIPT_ROLE, content=content, payload={"job_id": job_id})
        return _start_turn_with(db, session, message, _prompt_with_context(prompt, unseen), owner)
    return _wait_for_the_running_turn(
        db,
        session,
        AgentMessage(
            session_id=session.id,
            role=JOB_RECEIPT_ROLE,
            content=content,
            payload={"job_id": job_id, "undelivered": True, "deliver_as": owner.id},
        ),
    )


def _start_turn_with(db: Session, session: AgentSession, message: AgentMessage, prompt: str, actor: User) -> AgentMessage:
    """落库这一轮的由头(用户消息 / 回执),以 `actor` 的身份起一轮。调用方已经抢到了会话。"""
    db.add(message)
    db.commit()
    token = _mint_service_token(db, actor, session.id)
    _start_turn(session.id, prompt, token, actor_id=actor.id)
    db.refresh(message)
    return message


def _wait_for_the_running_turn(db: Session, session: AgentSession, message: AgentMessage) -> AgentMessage:
    """落库一条等这一轮结束的(排队的话 / 待送的回执),**再 drain 一次**。

    排队这个决定是「读 status」和「写消息」两步,中间那一轮完全可能跑完并 drain 过了 —— 那次 drain
    看到的队列还是空的,而这条消息随后才落库,于是它躺在一个 idle 的会话里,再也没有下一轮来捞它。
    用户看到的是「发过去没反应」。

    这一下补在写之后,所以看得见自己刚写的东西。上一轮还在跑的话它抢不到会话、直接让位,
    那条消息由那一轮结束时的 drain 接走 —— 两边都不会漏,也不会重。
    """
    db.add(message)
    db.commit()
    db.refresh(message)
    _drain_queue(session.id)
    return message


def post_user_message(
    db: Session,
    session: AgentSession,
    content: str,
    user: User,
    *,
    context: str | None = None,
    references: list[dict] | None = None,
    body_document: dict | None = None,
    origin_session_id: str | None = None,
    answers: dict | None = None,
    steer_if_running: bool = False,
) -> AgentMessage:
    """Store the user message and run the agent turn on a worker thread.

    `answers` 也是给回答用的:{问题: 选中项}。正文照旧要像用户自己说的话(模型读的是它),
    但**一次选择不该在对话里退化成一段自述** —— 结构留在这里,界面据此画回「问的是什么、
    选的是哪一项」,而不是一行「我选好了:…」。

    `steer_if_running` 是给**回答**用的:选择卡的答案、跳过的回执 —— 这条消息是对模型自己
    提的那个问题的回复,不是"用户碰巧提早打的下一句"。排队的默认语义在那里是错的:模型
    此刻正基于"还没拿到答案"往下走,而答案躺在队列里等这一轮跑完。用户看到的更糟 ——
    输入框上方冒出一条**他没写过**的消息,带着 Steer 和删除两个按钮。
    """
    # 模型收到的那一份可以比落库的正文多几样东西:引用清单、上下文集锦,以及"这条是别的
    # 会话发来的"信封。都不进 content —— content 是**用户在对话里看到的**那份。
    # 前两样和排队那条共用 user_prompt,免得两条路各拼各的(引用当初就是这么漏掉的)。
    prompt = user_prompt(
        content,
        {"references": references, "context": context},
        db=db,
        workspace_id=session.workspace_id,
    )
    # 再一样:失败的那几轮模型没见过(失败不回存 adapter_state),而用户以为它见过。
    prompt = _prompt_with_context(prompt, unseen_since_last_success(db, session))
    prompt = with_origin_envelope(prompt, origin_marker_for(origin_session_id))
    # 另一个智能体会话发来的通知:落库带结构化来源(前端画徽章靠它),
    # 且**不参与**会话自动命名 —— 标题应当是人提的第一件事,不是别的智能体的信封。
    origin_marker = origin_marker_for(origin_session_id)
    if not _claim_idle_session(db, session.id):
        # 回答走插话:抢不到会话说明有一轮在跑,而这条正是它等的东西。插进去成功就当场落库
        # (不带 queued 标),于是它像一条正常的用户消息出现在对话里,而不是队列里那种待办。
        # 插不进去(那一轮刚好结束了)就落回排队 —— 下面那次 drain 会接走它,不会掉进空里。
        if steer_if_running and steer_turn(session.id, prompt):
            message = AgentMessage(
                session_id=session.id,
                role="user",
                content=content,
                payload={
                    **({"references": references} if references else {}),
                    **({"body_document": body_document} if body_document else {}),
                    **({"context": context.strip()} if context and context.strip() else {}),
                    **({"answers": answers} if answers else {}),
                    **origin_marker,
                },
            )
            db.add(message)
            db.commit()
            db.refresh(message)
            return message
        # Queued, not steered. These are two different things and only one of them should be
        # the default: queuing waits for the whole reason-act loop to finish and then runs as
        # its own turn, which is what someone typing a follow-up almost always means. Steering
        # cuts into the running loop, changing what the agent does next — powerful, and wrong
        # to apply to every message someone happens to send early. It is opt-in per message
        # (steer_queued_message) the way Codex offers it as an action on the pending item.
        # The sender rides along: a queued turn is run later by a background thread, which has
        # no request and therefore no user to mint a service token for. The session does not
        # record an owner, so the message has to.
        # **落库之后再 drain 一次**(见 _wait_for_the_running_turn)。
        return _wait_for_the_running_turn(
            db,
            session,
            AgentMessage(
                session_id=session.id,
                role="user",
                content=content,
                payload={
                    "queued": True,
                    "queued_by": user.id,
                    **({"references": references} if references else {}),
                    **({"body_document": body_document} if body_document else {}),
                    **({"context": context.strip()} if context and context.strip() else {}),
                    **({"answers": answers} if answers else {}),
                    **origin_marker,
                },
            ),
        )
    # context 也要存:发出去的是 `_prompt_with_context(content, context)`,而 content 只是它的一半。
    # 排队那条路一直存着,直发这条没存 —— 于是同一件事有两种记录,轨迹上看到的提问不是模型
    # 收到的提问。不存的话这段上下文除了当场生效之外不留任何痕迹,事后无从复盘。
    message = AgentMessage(
        session_id=session.id,
        role="user",
        content=content,
        payload={
            **({"references": references} if references else {}),
            **({"body_document": body_document} if body_document else {}),
            **({"context": context.strip()} if context and context.strip() else {}),
            **({"answers": answers} if answers else {}),
            **origin_marker,
        },
    )
    if session.title == "新对话" and content.strip() and not origin_session_id:
        session.title = session_title(content)
    # 还没交给智能体的回执(只会是上一轮收尾和这条消息之间到的)搭这一轮的车,排在这条消息之前。
    # 先交再落这条:交出去的回执时间戳改成现在,这条消息落库在它们之后。
    receipts = _hand_over_receipts(db, session, before_user=True)
    return _start_turn_with(db, session, message, _with_receipts(prompt, receipts), user)


def mint_tool_token(db: Session, user: User) -> str:
    """Public alias — 出进程的一次性操作(上下文压缩、订阅登录/刷新)要一份和 turn 同级的短期凭据。"""
    return _mint_service_token(db, user)


def _mint_service_token(db: Session, user: User, agent_session_id: str | None = None) -> str:
    """turn 令牌带上**它属于哪次对话**——确认卡的归属从这里出发。

    此前归属是靠 sidecar 把 sessionId 一路转述到开卡请求体里的,而转述就可以被伪造:任何拿着
    同一份凭据的通道,填上别人的会话 id 就能把自己的动作挂进那次对话(三档权限模式下,那等于
    挂进别人开的自动放行)。铸令牌的这一刻正好知道答案,所以答案从这里出发。
    """
    return mint_service_session(db, user.id, agent_session_id=agent_session_id)


def _start_turn(session_id: str, prompt: str, token: str, *, actor_id: str | None = None) -> None:
    """开一轮。

    **流要在起线程之前备好。** 界面拿到 POST 的回应之后才去连 `/stream`,而这一轮的流状态
    此前是在工作线程里建的 —— 中间那个窗口里 `get_stream_state` 返回的是「没有回合在跑」,
    SSE 当场就把连接关掉,于是那一整轮的轨迹面板是空的(思考、工具卡片一条都不出现,
    直到回合结束才一次性补上)。窗口很窄,所以它表现为「偶尔整轮没有轨迹」。

    备好流是纯内存操作,放在调用方这一侧,POST 返回时它已经在了。

    **语言跟着发消息的人走。** 工作线程不继承请求的 ContextVar,不带过去的话,这一轮失败时
    写进对话里的那句话(「没有选好对话模型」「执行失败」)永远是缺省语言 —— 英文界面的
    对话里冒出一句中文。对话记录本来就是写下那一刻的文字,和模型的回答一样不再重翻。
    """
    _stream_reset(session_id)
    locale = get_current_locale()

    def run() -> None:
        set_current_locale(locale)
        _run_turn_thread(session_id, prompt, token, actor_id=actor_id)

    threading.Thread(target=run, daemon=True, name=TURN_THREAD_NAME).start()


def _failed_turn_timeline(session_id: str) -> dict:
    """失败那一轮已经发生过的过程,整理成和成功轮同一种形状。

    **取不到也不能让收尾崩掉** —— 这里已经在 except 里了,再抛一次就没人写那条失败消息,
    会话会永远卡在 running。所以整段兜住,取不到就当这一轮没有过程。
    """
    try:
        timeline = _timeline_for_payload(get_stream_state(session_id), "")
    except Exception:  # noqa: BLE001 —— 收尾路径:有记录更好,没有也不能连累错误消息落库
        logger.exception("failed to capture the timeline of a failed turn")
        return {}
    return {"timeline": timeline} if timeline else {}


def _run_turn_thread(session_id: str, prompt: str, token: str, *, actor_id: str | None = None) -> None:
    api_base = f"http://{settings.backend_host}:{settings.backend_port}"
    final_text = ""
    turn_started = time.monotonic()
    provider_profile_id: str | None = None
    provider_vendor = ""
    provider_model = ""
    result: TurnResult | None = None
    #: 准备或运行时的失败,留到落库那一段里按原样抛出 —— 和那里自己抛的错走同一组 except。
    failure: BaseException | None = None

    # ---- 1. 准备:短会话,读完就还连接 ----
    # **跑模型的那几分钟不占数据库连接。** 此前整轮包在一个会话里:一轮对话几分钟,连接就被钉几分钟,
    # 而这期间它唯一的用处是最后写一条消息。几个会话同时在想,连接池就空了,别的请求排在它们后面。
    with SessionLocal() as db:
        session = db.get(AgentSession, session_id)
        if session is None:
            return
        #: 先记下:收尾时会话可能已被删掉,那时再读它的属性会抛。
        origin = session.origin
        # Everything below is caught: a failure while resolving the provider (or building the
        # prompt) must still write an error message and reset session.status — otherwise the
        # worker dies silently and the session hangs in "running" forever.
        try:
            system_prompt = build_system_prompt(db, session)
            # pi 适配器的对话模型:优先用会话选定的供应商+模型,否则回退第一个启用供应商及其默认模型
            provider_dict: dict | None = None
            agent_model: str | None = None
            if session.adapter == "pi":
                # 外部渠道的会话(飞书一个群一个)没有主人:用的是**发这条消息的人**的钥匙与默认模型,
                # 和给这一轮铸令牌的是同一个人。
                provider_dict, agent_model, profile = resolve_chat_provider(
                    db, session.provider_profile_id, session.model or "", user_id=session.owner_user_id or actor_id
                )
                if profile is not None:
                    provider_profile_id = profile.id
                    provider_vendor = profile.vendor
                    provider_model = agent_model or ""
            turn_kwargs = {
                "prompt": prompt,
                "system_prompt": system_prompt,
                "api_base": api_base,
                "token": token,
                "thinking_level": session.thinking_level or "off",
                "provider": provider_dict,
                "model": agent_model,
                "workspace_id": session.workspace_id,
                "adapter_state": session.adapter_state,
                "session_key": session.id,
                "images": _attached_images(db, session.workspace_id, prompt),
            }
            adapter = session.adapter
        except Exception as exc:  # noqa: BLE001 —— 见上
            failure = exc

    # ---- 2. 运行:不持有任何数据库会话 ----
    if failure is None:
        try:
            result = run_turn(
                adapter,
                on_delta=lambda delta: _stream_append(session_id, delta),
                on_tool=lambda event: _stream_tool_event(session_id, event),
                on_thinking=lambda event: _stream_thinking(session_id, event),
                **turn_kwargs,
            )
        except Exception as exc:  # noqa: BLE001 —— 落库那一段按类型处理
            failure = exc

    # ---- 3. 落库:再开一个短会话 ----
    with SessionLocal() as db:
        session = db.get(AgentSession, session_id)
        if session is None:
            # 这一轮跑着的时候会话被删了:没有地方写结果,但令牌照样要收回、流照样要收尾。
            revoke_session(db, token)
            db.commit()
            _stream_finish(session_id, final_text)
            return
        try:
            if failure is not None:
                raise failure
            assert result is not None
            # 本地模型的 byte-fallback token(<0xF0>… 字面串)在落库前重组回 UTF-8。
            final_text = decode_byte_fallback(result.text)
            if result.adapter_state is not None:
                session.adapter_state = result.adapter_state  # pi 多轮记忆:回存序列化消息
            stream_state = get_stream_state(session_id)
            timeline = _timeline_for_payload(stream_state, final_text)
            # Never persist a blank assistant turn: an empty reply with no tool calls means the
            # model call failed somewhere upstream. Surfacing it as an empty bubble is what made
            # provider misconfiguration look like "nothing happened".
            if not final_text.strip() and not timeline:
                raise SidecarError(tr("agentErr_emptyReply"))
            usage = _usage_from_started(turn_started, stream_state.get("first_token_at"))
            usage["metering"] = _turn_metering(prompt, final_text, result.usage)
            prompt_snapshot = _prompt_snapshot(db, session.id, system_prompt)
            assistant_message = AgentMessage(
                session_id=session.id,
                role="assistant",
                content=final_text,
                payload={
                    "usage": usage,
                    # 系统提示变了才记 —— 轨迹上的每条 SYSTEM 都是一次真实变化。
                    **({"prompt": prompt_snapshot} if prompt_snapshot else {}),
                    # 上下文水位挂在最近一条助手消息上,前端据此画进度条 —— 不另建一张表:
                    # 它天然随对话推进而更新,且历史消息保留着当时的水位,回看时也说得通。
                    **({"context": result.context} if result.context else {}),
                    # 压缩必须被看见:静默压缩会让用户以为模型"忘了"早期内容。
                    **({"compaction": result.compaction} if result.compaction else {}),
                    **({"timeline": timeline} if timeline else {}),
                },
            )
            db.add(assistant_message)
            db.flush()
            if provider_vendor or provider_model:
                # 记账的形状交给 billable(归属、耗时、幂等、落库);这里只报计量。
                # 成本要写进消息 payload,而它是落库时才算出来的 —— 所以在 with 块之后读回。
                with billable(
                    db,
                    capability="chat",
                    operation="agent_turn",
                    workspace_id=session.workspace_id,
                    provider_profile_id=provider_profile_id,
                    provider=provider_vendor,
                    model=provider_model,
                    source_type="agent_message",
                    source_id=assistant_message.id,
                    agent_message_id=assistant_message.id,
                    idempotency_key=f"agent-message:{assistant_message.id}",
                ) as call:
                    call.meter(usage["metering"], raw=result.usage or {})
                event = call.event
                if event is not None:
                    usage["cost"] = {
                        "cost_micros": event.cost_micros,
                        "currency": event.currency,
                        "confidence": event.cost_confidence,
                    }
                # **只更新 usage(它多了 cost),不重建整个 payload。** 这里曾经写成
                # `{"usage": ..., "timeline": ...}` —— 把第一次构造时写进去的 prompt 快照、
                # 上下文水位、压缩标记整个覆盖丢了。表现是轨迹里永远见不到 SYSTEM/CONTEXT 行,
                # 而写入代码、读取代码单看都是对的(真机上最近 300 条消息里快照 0 条)。
                assistant_message.payload = {**(assistant_message.payload or {}), "usage": usage}
        except SidecarError as exc:
            # **失败也回存记忆(拿得到的话)。** 这一轮是跑过的:失败点之前的工具调用真的发生了,
            # 它们改过的东西留在库里。不回存的话记忆回滚到上一次成功,模型下次醒来不知道自己
            # 已经做过那些事,于是会再做一遍 —— 而它做的是建项目、改时间线这类有副作用的事。
            # 拿不到就保持原样(sidecar 整个没了),那时确实无从补起,由 unseen_since_last_success
            # 把「有过一轮、失败了」这件事补给它。
            if getattr(exc, "adapter_state", None) is not None:
                session.adapter_state = exc.adapter_state
            usage = _usage_from_started(turn_started)
            usage["metering"] = _turn_metering(prompt, "", getattr(exc, "usage", None))
            assistant_message = AgentMessage(
                session_id=session.id,
                role="assistant",
                # 说得出原因就说原因 —— 「请稍后重试」对一次超时是错的建议。
                content=getattr(exc, "human", "") or tr("agentErr_turnFailed"),
                error=str(exc)[:800],
                payload={
                    "usage": usage,
                    # **失败的那一轮,过程照样要留下来。** 上面那段已经说了失败点之前的工具调用
                    # 真的发生过 —— 记忆回存了,而给人看的记录此前没有:一次跑了三分钟、调了十来次
                    # 工具的对话,只要最后一步断线,用户看到的就只剩一句「执行失败」。模型知道自己
                    # 做过什么,用户不知道,这是最糟的一种不对称。
                    **_failed_turn_timeline(session_id),
                    **({"context": exc.context} if getattr(exc, "context", None) else {}),
                },
            )
            db.add(assistant_message)
            db.flush()
            if provider_vendor or provider_model:
                # 异常已经被这里接住了,billable 看不见 —— 显式标失败。失败的轮次同样花了钱。
                with billable(
                    db,
                    capability="chat",
                    operation="agent_turn",
                    workspace_id=session.workspace_id,
                    provider_profile_id=provider_profile_id,
                    provider=provider_vendor,
                    model=provider_model,
                    source_type="agent_message",
                    source_id=assistant_message.id,
                    agent_message_id=assistant_message.id,
                    idempotency_key=f"agent-message:{assistant_message.id}",
                ) as call:
                    call.meter(usage["metering"], raw=getattr(exc, "usage", None) or {})
                    call.mark_failed()
        except Exception as exc:  # worker threads must never die silently
            logger.exception("Agent turn crashed")
            usage = _usage_from_started(turn_started)
            usage["metering"] = _turn_metering(prompt, "", None)
            assistant_message = AgentMessage(
                session_id=session.id,
                role="assistant",
                content=tr("agentErr_turnCrashed"),
                error=str(exc)[:800],
                payload={"usage": usage, **_failed_turn_timeline(session_id)},
            )
            db.add(assistant_message)
            db.flush()
            if provider_vendor or provider_model:
                # 异常已经被这里接住了,billable 看不见 —— 显式标失败。失败的轮次同样花了钱。
                with billable(
                    db,
                    capability="chat",
                    operation="agent_turn",
                    workspace_id=session.workspace_id,
                    provider_profile_id=provider_profile_id,
                    provider=provider_vendor,
                    model=provider_model,
                    source_type="agent_message",
                    source_id=assistant_message.id,
                    agent_message_id=assistant_message.id,
                    idempotency_key=f"agent-message:{assistant_message.id}",
                ) as call:
                    call.meter(usage["metering"])
                    call.mark_failed()
        finally:
            session.status = "idle"
            session.updated_at = now()
            # Revoke the service token this turn was given. It is minted per turn so the MCP
            # server can call back into the API, and nothing ever removed it — AuthSession has
            # no expiry, so every chat turn left a permanent full-privilege credential in the
            # database. A long-running install accumulated one per message, forever.
            revoke_session(db, token)
            try:
                db.commit()
            except Exception:  # noqa: BLE001
                # The session can be deleted while its turn is still running. There is then no
                # row to mark idle, and letting this propagate kills the thread before
                # _stream_finish — leaving the UI spinning on a conversation that is gone.
                logger.warning("Could not finalise session %s; it may have been deleted", session_id)
                db.rollback()
            _stream_finish(session_id, final_text)
    # 外部渠道(飞书……)把这一轮的结果送回原会话。在 drain 之前:排队的下一轮不该抢在这一轮的回复前面。
    origins.turn_finished(origin, session_id)
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
        if session is None:
            return
        # **先抢占,再看队列。** 「读到 idle」和「置成 running」如果不是一步,两个 drain 会同时
        # 通过检查、同时取走同一条消息、同时起一轮 —— 用户看到那条消息被回答了两遍。
        # 条件更新让数据库来裁决:rowcount 是 0 就是别人抢到了,直接让位。
        claimed = _claim_idle_session(db, session_id, only_if_queued=True)
        db.commit()
        if not claimed:
            return
        db.refresh(session)
        pending = _queued_messages(db, session)
        receipts = _undelivered_receipts(db, session)
        if not pending and not receipts:
            # 抢的时候队列里还有,读的时候没了(那条刚被取消 / 被引导进了别的轮)。必须把 status
            # 放回去,否则这个会话永远停在 running,之后每一条消息都会被当成"正忙"排进一个再也
            # 不会被 drain 的队列。
            session.status = "idle"
            db.commit()
            return
        # **攒下的回执一次交出去**,不是每条各起一轮:智能体连着提交一串配音时,它们在这一轮里陆续跑完,
        # 此前每条都在这一轮之后各跑一轮(用户截图:输入框上方排了七八条)。有人排了话,回执就搭那一轮的车
        # —— 排在他那句话之前交代,智能体回答他的时候已经知道这些任务跑完了;只有回执就自己起一轮。
        message = pending[0] if pending else None
        if message is not None:
            actor_id = (message.payload or {}).get("queued_by")
        else:
            actor_id = (receipts[0].payload or {}).get("deliver_as")
        owner = db.get(User, actor_id) if actor_id else None
        handed = _hand_over_receipts(db, session, before_user=message is not None)
        if message is not None:
            _unqueue(db, message)
        if owner is None:
            # Without a sender there is no credential to run as. Clearing the flag anyway so it
            # is not retried on every subsequent turn — a message that silently reappears
            # forever is worse than one that visibly did not run.
            logger.warning("queued message / receipt in session %s has no sender; not running it", session_id)
            session.status = "idle"
            db.commit()
            return
        token = _mint_service_token(db, owner, session_id)
        if message is not None:
            payload = message.payload or {}
            content = user_prompt(message.content, payload, db=db, workspace_id=session.workspace_id)
            # 排队那条也要补信封:它和直发走的是同一件事,只是晚一点跑。漏在这儿的话,
            # 「对方正忙」时收到的消息,模型就不知道它是谁发的。
            content = _with_receipts(with_origin_envelope(content, payload), handed)
        else:
            content = handed
        # 提交排在拼完提示词之后:拼的时候可能为挂着的文档补起一次解析(documents.reading.attachment_context),
        # 解析任务在提交之后才开跑(jobs.dispatch_job)。
        db.commit()
    _start_turn(session_id, content, token, actor_id=owner.id)


def reconcile_orphaned_agent_sessions(db: Session) -> int:
    """把重启前卡在 running 的会话拨回 idle(与 reconcile_orphaned_jobs 同理)。

    turn 跑在进程内的 daemon 线程 + sidecar 子进程上,后端一重启(开发 --reload
    尤其频繁)线程即死,_run_turn_thread 的 finally 永远执行不到 —— 会话从此
    永远「思考中」,前端只是如实转述。启动时统一拨回,并补一条可见的中断说明,
    否则那轮用户消息看起来石沉大海。

    **那一轮留下的确认卡也要一起作废。** 不作废的话,对话上面写着「已中断,请重新发送」,
    下面那张卡还亮着三个按钮等你点 —— 而 approve_confirmation 是**当场执行工具**的
    (不是唤醒某个还在等的线程),点下去真的会把浏览器打开、把节点加上,而结果没有任何一轮
    对话去接收。所以这不是"点了没反应"那种小事,是一个已经没有上下文的动作仍然可以被执行。
    """
    stale = db.scalars(select(AgentSession).where(AgentSession.status == "running")).all()
    for session in stale:
        session.status = "idle"
        db.add(
            AgentMessage(
                session_id=session.id,
                role="assistant",
                content=INTERRUPTED_NOTICE,
                error="backend restarted mid-turn",
            )
        )
    if stale:
        # 只作废**这些会话**的卡。session_id 为空的那批来自 MCP / 飞书等外部智能体,
        # 它们是另一条生命周期(进程可能还活着、还在等人点),不该被这里顺手清掉。
        db.execute(
            update(ToolConfirmation)
            .where(
                ToolConfirmation.session_id.in_([session.id for session in stale]),
                ToolConfirmation.status == "pending",
            )
            .values(status="cancelled", error="backend restarted mid-turn", resolved_at=now())
        )
        db.commit()
    return len(stale)


#: 中断说明的原文。外部渠道(飞书等)要把同一句话发回聊天里 —— 只写进库的话,
#: 桌面端看得到,而在飞书里发消息的那个人只看到一片沉默,和"还在处理"分辨不出来。
INTERRUPTED_NOTICE = "上一轮对话因后端重启而中断,请重新发送。"


def interrupted_external_sessions(db: Session, origin: str) -> list[tuple[str, str, str]]:
    """刚被拨回 idle、且来自某个外部渠道的会话 → [(external_key, 通知文案, 消息 id)]。

    给调用方(main.py 的启动流程)去把中断说明发回原聊天。**不在 host 里直接发**:
    host 属于 ai 层,而渠道在 integrations 层 —— 反过来 import 就成了环(领域层回调集成层
    那个环这个仓库已经踩过一次)。所以这里只报告"谁被中断了",发不发、怎么发由组合层决定。

    **发过的不再报。** 判据是"最后一条消息带中断标记",而聊天里之后没人说话的话,它就
    一直是最后一条 —— 开发模式 --reload 频繁重启,每次启动都把同一句话再发一遍,飞书那头
    收到的是一串「请重新发送」(真机反馈)。所以调用方发成功后要调 mark_interrupt_notified,
    这里跳过已标记的。
    """
    sessions = db.scalars(
        select(AgentSession).where(AgentSession.origin == origin, AgentSession.external_key.isnot(None))
    ).all()
    out: list[tuple[str, str, str]] = []
    for session in sessions:
        last = session.messages[-1] if session.messages else None
        if last is None or last.error != "backend restarted mid-turn":
            continue
        if (last.payload or {}).get("interrupt_notified"):
            continue
        out.append((session.external_key or "", INTERRUPTED_NOTICE, last.id))
    return out


def mark_interrupt_notified(db: Session, message_id: str) -> None:
    """记下「这条中断说明已经发到外部渠道了」,下次启动不再重发。"""
    message = db.get(AgentMessage, message_id)
    if message is None:
        return
    message.payload = {**(message.payload or {}), "interrupt_notified": True}
    db.commit()


def cancel_queued_message(db: Session, session: AgentSession, message_id: str) -> list[str]:
    """Drop a message that has not run yet."""
    message = db.get(AgentMessage, message_id)
    if message is None or message.session_id != session.id or not (message.payload or {}).get("queued"):
        raise HostError("agentErr_messageAlreadyRunning")
    db.delete(message)
    db.flush()
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
        raise HostError("agentErr_queuedMessageMissing")
    if not steer_turn(session.id, _prompt_with_context(message.content, (message.payload or {}).get("context"))):
        return False
    _unqueue(db, message)
    db.flush()
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


def compact_session_context(db: Session, session: AgentSession, user: User) -> dict:
    """手动整理上下文(界面上的「立即压缩」)。

    压缩本身要调一次模型做摘要,所以它是用户主动触发而不是后台悄悄跑。压完把新的
    adapter_state 回存,并在对话里留一条 system 消息 —— **压缩必须被看见**:静默压缩会让
    用户以为模型"忘了"早期内容,而实际上是我们主动移走的。
    """
    provider_dict, agent_model, _profile = resolve_chat_provider(db, session.provider_profile_id, session.model or "", user_id=session.owner_user_id)
    result = compact_session(
        api_base=f"http://{settings.backend_host}:{settings.backend_port}",
        token=mint_tool_token(db, user),
        provider=provider_dict,
        model=agent_model,
        adapter_state=session.adapter_state,
    )
    if result.adapter_state is not None:
        session.adapter_state = result.adapter_state
    if result.compaction:
        db.add(
            AgentMessage(
                session_id=session.id,
                role="system",
                content="",
                payload={"compaction": result.compaction, **({"context": result.context} if result.context else {})},
            )
        )
    db.commit()
    # 压完的水位**在这边重算**,不用 sidecar 回报的那份:后者只有 {tokens, window},没有分项。
    # 两条路给两种形状,界面就得判断"这次有没有明细" —— 而那正是同一个数有两个来源的代价。
    return {"context": session_context(db, session), "compaction": result.compaction}


def tool_definition_tokens(db: Session, user_id: str | None = None) -> int:
    """工具定义每轮重发一遍占掉多少 —— 这个应用里通常是**最大的一块**。

    按 sidecar 实际发出去的形状估:名字 + 描述 + 参数 schema 的 JSON。它不随对话增长,所以
    一条消息都没有的会话也已经占掉了一大块 —— 那正是这一屏要说清的事。
    """
    from app.domain.agent.tool_manifest import agent_tool_specs

    payload = json.dumps(
        [
            {"name": spec.name, "description": spec.description, "parameters": spec.parameters}
            for spec in agent_tool_specs(db, user_id)
        ],
        ensure_ascii=False,
    )
    return math.ceil(len(payload) / CHARS_PER_TOKEN)


def session_context(db: Session, session: AgentSession) -> dict | None:
    """会话当前的上下文水位。

    没配供应商时返回 None(整条不显示)。但**窗口取不到不等于未知**:sidecar 那边一直在用
    sidecar 会按端点位置选择回退值，所以这里也走同一规则 —— 藏起来会让用户以为"没有上限"。
    """
    try:
        provider_dict, agent_model, profile = resolve_chat_provider(
            db,
            session.provider_profile_id,
            session.model or "",
            user_id=session.owner_user_id,
        )
    except Exception:  # noqa: BLE001 — 没配供应商时不该让会话详情整个失败
        return None
    if not provider_dict or not agent_model:
        return None
    window = provider_dict.get("context_window")
    if not window:
        # 订阅计划的窗口在 pi 的目录里,后端拿不到;登录时存下的 model_catalog 有这份。
        # 会话没有显式选模型时,resolve_chat_provider 会落到用户的默认模型。此时
        # session.provider_profile_id 仍为空,但目录属于刚解析出来的 profile —— 继续拿
        # session 上的空值去查会错过真实窗口。结果就是 K3 的 1M 窗口显示成通用回退值。
        resolved_profile_id = getattr(profile, "id", None) or session.provider_profile_id
        for entry in session_model_catalog(db, resolved_profile_id, session.owner_user_id):
            if entry.get("id") == agent_model:
                window = entry.get("contextWindow") or entry.get("context_window")
                break
    window = int(window) if window else fallback_context_window(str(provider_dict.get("base_url") or ""))
    return {
        "tokens": context_tokens(session.adapter_state),
        "window": window,
        # 分项由**后端**给:算它需要系统提示的实际内容和工具清单,那两样都在服务端。前端猜不
        # 出来,而猜出来的分项比没有分项更糟 —— 它看起来是测量结果。
        **context_breakdown(
            session.adapter_state,
            system_prompt=build_system_prompt(db, session),
            tool_tokens=tool_definition_tokens(db, session.owner_user_id),
            window=window,
        ),
    }


def session_model_catalog(db: Session, profile_id: str | None, user_id: str | None) -> list[dict]:
    """订阅计划登录后存下的模型目录;没有就是空列表。"""
    if not profile_id:
        return []

    from app.domain.providers import credentials as provider_credentials

    # 目录跟着钥匙走:两个人的订阅档位可以不一样,拿别人的目录去算窗口是错的。
    mine = provider_credentials.get(db, profile_id, user_id) if user_id else None
    catalog = mine.model_catalog if mine is not None else None
    return [entry for entry in (catalog or []) if isinstance(entry, dict)]
