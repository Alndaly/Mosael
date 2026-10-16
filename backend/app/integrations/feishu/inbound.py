"""收到的飞书消息 → 智能体 → 回复。

飞书(Lark)双向接入,移植自旧项目的长连接方案:lark_oapi.ws.Client 长连接收消息(无需公网 webhook),
tenant_access_token 发消息。每个机器人一个独立子进程(见 connections;SDK 的事件循环是模块级共享的,
进程才是安全隔离边界),但子进程**只转发事件**:消息经管道回到主进程,由这里的 handle_incoming 交给
智能体宿主层的外部会话(external_key = feishu:bot:chat),以**发消息的那个绑定成员**的身份跑,回复
由 deliver_turn 发回原会话。
"""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import threading
import time
from collections import OrderedDict
from dataclasses import replace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.i18n import DEFAULT_LOCALE, t
from app.db.models import AgentMessage, AgentSession, FeishuBot, Job, Workflow, WorkflowTrigger, WorkflowTriggerEvent
from app.domain.agent import origins
from app.domain.agent.host import get_or_create_external_session, post_user_message
from app.domain.feishu import bindings
from app.domain.jobs import register_settle_listener
from app.domain.triggers import IncomingMessage
from app.domain.triggers import dispatch as trigger_dispatch
from app.integrations.feishu import client

logger = logging.getLogger(__name__)

MENTION_RE = re.compile(r"^(@_user_\d+\s*)+")


def extract_text(content_json: str) -> str:
    """从消息 content 里取纯文本。text 与 post(富文本)都收 —— 用户带格式粘贴一段话,
    飞书发过来的就是 post,而它对用户来说和普通文字没有任何区别。"""
    try:
        parsed = json.loads(content_json or "{}")
    except ValueError:
        #: 用户发的这条消息内容解不开,bot 表现得像没收到 —— 静默丢消息是最坏的,留痕。
        logger.warning("飞书消息的 content 解不开,这条按没有文本处理: %.200r", content_json)
        return ""
    if isinstance(parsed.get("text"), str):
        return MENTION_RE.sub("", parsed["text"]).strip()
    # post: {"title": ..., "content": [[{"tag":"text","text":"..."}, {"tag":"a","text":...}], ...]}
    pieces: list[str] = [str(parsed.get("title") or "")]
    blocks = parsed.get("content")
    if isinstance(blocks, list):
        for line in blocks:
            if not isinstance(line, list):
                continue
            pieces.append("".join(str(run.get("text") or "") for run in line if isinstance(run, dict)))
    return MENTION_RE.sub("", "\n".join(piece for piece in pieces if piece)).strip()


_seen: OrderedDict[str, float] = OrderedDict()
_seen_lock = threading.Lock()


def seen_recently(message_id: str, window_seconds: float = 300) -> bool:
    with _seen_lock:
        horizon = time.time() - window_seconds
        while _seen and next(iter(_seen.values())) < horizon:
            _seen.popitem(last=False)
        if message_id in _seen:
            return True
        _seen[message_id] = time.time()
        return False


CAPABILITY_NOTES = {
    "readonly": "本会话为只读档:只允许使用只读工具(list/inspect),不要提交任何确认卡。",
    "editor": "本会话为编辑档:可以提交时间线修改与生成的确认卡,等待用户在 Mosael 中批准。",
    "full": "本会话为完整档:可使用全部工具,变更仍需用户在 Mosael 中批准确认卡。",
}


#: 能读进来的消息类型。其余类型不是丢掉,而是回一句说明 —— 见 _describe_unsupported。
SUPPORTED_MESSAGE_TYPES = frozenset({"text", "post", "image"})

#: 智能体看不懂、但**工作流触发器**可能接的消息类型:文件与视频(ADR 0065)。
#: 没有触发器认它们时,照旧回一句「看不了」(见 _describe_unsupported)。
TRIGGERABLE_MESSAGE_TYPES = frozenset({"file", "media"})


def _image_keys(message_type: str, content_json: str) -> list[str]:
    """消息里的图片 file_key。image 消息一张;post(富文本)可以内嵌多张。"""
    try:
        parsed = json.loads(content_json or "{}")
    except ValueError:
        logger.warning("飞书消息的 content 解不开,这条按没有图片处理: %.200r", content_json)
        return []
    if message_type == "image":
        key = str(parsed.get("image_key") or "")
        return [key] if key else []
    keys: list[str] = []
    for line in parsed.get("content") or []:
        if not isinstance(line, list):
            continue
        for run in line:
            if isinstance(run, dict) and run.get("tag") == "img" and run.get("image_key"):
                keys.append(str(run["image_key"]))
    return keys


def _file_attachment(message_type: str, content_json: str) -> tuple[str, str]:
    """文件 / 视频消息里的 `(file_key, file_name)`。别的类型没有,给两个空串。"""
    if message_type not in TRIGGERABLE_MESSAGE_TYPES:
        return "", ""
    try:
        parsed = json.loads(content_json or "{}")
    except ValueError:
        logger.warning("飞书消息的 content 解不开,这条按没有附件处理: %.200r", content_json)
        return "", ""
    if not isinstance(parsed, dict):
        return "", ""
    return str(parsed.get("file_key") or ""), str(parsed.get("file_name") or "")


def _content_type_of(name: str) -> str:
    """按文件名猜一个 MIME。只是给探测器的提示:真正是什么由回形针那条路自己探。"""
    return mimetypes.guess_type(name or "")[0] or "application/octet-stream"


def _ingest_attachments(
    bot: FeishuBot, workspace_id: str, message_id: str, message_type: str, content_json: str
) -> tuple[list[str], str]:
    """把这条消息里的图片 / 文件 / 视频下载进素材库,返回 `(素材 id, 文件名)`。

    **走素材库而不是直接塞给模型**:桌面端的回形针也是这么做的(上传成素材 → 在提示里引用),
    智能体分析图片靠的是 analyze_asset 这个工具。图片那条路从第一天起就是这样;文件与视频
    (触发器用得到,见 ADR 0065)走的是同一个 `import_binary_asset` —— 于是飞书发来的东西此后
    在素材库里也找得到、能复用,而不是只在那一轮对话里存在过。
    """
    from app.domain.assets.importer import import_binary_asset

    wanted: list[tuple[str, str, str, str]] = [
        (key, "image", "image/jpeg", f"feishu-{message_id[-8:]}-{index + 1}.jpg")
        for index, key in enumerate(_image_keys(message_type, content_json)[:MAX_INBOUND_IMAGES])
    ]
    file_key, file_name = _file_attachment(message_type, content_json)
    if file_key:
        wanted.append((
            file_key,
            "file",
            _content_type_of(file_name),
            file_name or f"feishu-{message_id[-8:]}",
        ))

    asset_ids: list[str] = []
    for key, kind, content_type, name in wanted:
        try:
            data = client.download_message_resource(bot, message_id, key, kind)
        except Exception:  # noqa: BLE001 —— 一份下不来不该让整条消息失败
            logger.warning("feishu %s download failed key=%s", kind, key, exc_info=True)
            continue
        with SessionLocal() as db:
            asset = import_binary_asset(
                db,
                workspace_id=workspace_id,
                project_id=None,
                data=data,
                original=name,
                content_type=content_type,
                source="feishu",
            )
            asset_ids.append(asset.id)
    return asset_ids, file_name


#: 一条消息最多收几张图。飞书一次能发一组,而每张都要下载 + 探测 + 生成缩略图。
MAX_INBOUND_IMAGES = 9


def _describe_unsupported(message_type: str) -> str:
    known = {
        "file": "文件",
        "audio": "语音",
        "media": "视频",
        "sticker": "表情",
        "folder": "文件夹",
        "share_chat": "群名片",
        "share_user": "个人名片",
    }
    what = known.get(message_type, f"「{message_type}」类型的消息")
    return f"我暂时看不了{what}。可以发文字或图片给我,或者把文件先传进 Mosael 的素材库再让我处理。"


def handle_incoming(
    bot_id: str,
    chat_id: str,
    message_id: str,
    sender_open_id: str = "",
    *,
    message_type: str = "text",
    content_json: str = "",
) -> None:
    """主进程里跑(worker 只负责把长连接收到的事件转过来):把一条飞书消息交给**和桌面端同一条**
    turn 管线(host.post_user_message),以**发消息的那个绑定成员**的身份跑。未绑定的人被拒。

    此前这里是第二份 turn 实现(自己拼提示、解析供应商、调 run_turn、落库),而且跑在 worker
    子进程里 —— 桌面端的排队、失败轮留轨迹、计费、失败也回存记忆,飞书一样都没有。现在:

    - 会话正忙时这条**排队**,轮到它时照样回复(以前是回一句「上一条还在处理中」就丢掉)。
    - 回复由 origins 的 turn_finished 钩子送回(见文件末尾的登记),和这一轮在哪条线程跑完无关。

    **这一轮之前还有一道**:先问工作流触发器认不认这条消息(ADR 0065)。认了这条消息就归它
    ——不喂给智能体;没人认领才照旧走上面那条管线。用户发过来的东西两种收场都要有回应。
    """
    if seen_recently(message_id):
        return
    text = extract_text(content_json)
    image_keys = _image_keys(message_type, content_json)
    file_key, file_name = _file_attachment(message_type, content_json)
    with SessionLocal() as db:
        bot = db.get(FeishuBot, bot_id)
        if bot is None or not bot.enabled:
            return
        if message_type not in SUPPORTED_MESSAGE_TYPES and message_type not in TRIGGERABLE_MESSAGE_TYPES:
            # 说一句,而不是沉默。用户发过来什么都得到回应,哪怕是"我看不了这个"。
            client.send_text(bot, chat_id, _describe_unsupported(message_type))
            return
        if not text and not image_keys and not file_key:
            return
        # Identify the human behind the message. No open_id → can't attribute → refuse.
        user = bindings.resolve_sender(db, bot.workspace_id, sender_open_id) if sender_open_id else None
        if user is None:
            # An unbound sender may be redeeming a one-time bind code they got in-app.
            redeemed = bindings.redeem_bind_code(db, bot.workspace_id, sender_open_id, text) if sender_open_id else None
            db.commit()  # 这条消息就是一次用例:兑了码就在回话之前落库
            if redeemed is not None:
                client.send_text(bot, chat_id, f"绑定成功,你好 {redeemed.username}!之后直接对我说话即可。")
            else:
                client.send_text(
                    bot,
                    chat_id,
                    "你还没有绑定 Mosael 账号,无法使用本机器人。请在 Mosael『设置 → 飞书机器人』生成绑定码,"
                    "然后把绑定码直接发给我完成绑定。",
                )
            return
        #: **只有绑定过的人能驱动触发器**(ADR 0065 §4):上面那一道就是它的门槛 —— 未绑定的消息
        #: 在这里已经回头了,连匹配都轮不到。触发器跑起来花的是配置它那个人的钥匙和额度。
        message = IncomingMessage(
            workspace_id=bot.workspace_id,
            bot_id=bot.id,
            chat_id=chat_id,
            message_id=message_id,
            sender_open_id=sender_open_id,
            message_type=message_type,
            text=text,
            file_name=file_name,
        )
        #: **先问谁认这条消息,再决定去不去下载附件。** 下载要调飞书、落盘、探测、生成缩略图
        #: (文件与视频还要跑 ffprobe)—— 没人认领时一个字节都不该去下。
        claimed, skipped = trigger_dispatch.claimable(db, message)
        # 图片下载要几秒(下载 + 探测 + 缩略图),不该占着数据库会话;而 bot 是纯配置,
        # 出了 session 只用它的 id/app_id/app_secret 调 REST,detached 也够用。
        db.expunge(bot)
        workspace_id = bot.workspace_id

    if claimed:
        _run_triggers(bot, message, claimed, skipped, message_type, content_json)
        return

    if message_type not in SUPPORTED_MESSAGE_TYPES:
        #: 走到这里 = 文件 / 视频,**而没有任何触发器接它**:回到最开始那句话,行为和以前一模一样。
        client.send_text(bot, chat_id, _describe_unsupported(message_type))
        return

    if image_keys:
        asset_ids, _ = _ingest_attachments(bot, workspace_id, message_id, message_type, content_json)
        if not asset_ids:
            client.send_text(bot, chat_id, "图片没能取回来(飞书资源下载失败),换一张或稍后再试。")
            return
        # 图片先入素材库,再把素材 id 写进提示 —— 智能体靠 analyze_asset 看图,和桌面端
        # 回形针走的是同一条路(上传成素材 → 在提示里引用),不是给飞书单开一套。
        note = (
            f"[用户发来 {len(asset_ids)} 张图片,已存入素材库,素材 id:{'、'.join(asset_ids)}。"
            "需要看图就用 analyze_asset。]"
        )
        text = f"{text}\n{note}" if text else note

    # 「码字中」指示:给用户那条消息贴 Typing 反应,飞书客户端渲染成动画输入指示。
    # **先贴再交**:这一轮可能在 post_user_message 返回之前就跑完了,收尾时得找得到它。
    typing_reaction = client.add_reaction(bot, message_id, client.REACTION_TYPING)
    with SessionLocal() as db:
        session = get_or_create_external_session(
            db,
            workspace_id=workspace_id,
            origin="feishu",
            external_key=f"feishu:{bot.id}:{chat_id}",
            title=f"飞书 · {bot.name}",
        )
        user = bindings.resolve_sender(db, workspace_id, sender_open_id)
        if user is None:
            if typing_reaction:
                client.remove_reaction(bot, message_id, typing_reaction)
            return
        _awaiting(session.id, message_id, typing_reaction)
        try:
            post_user_message(db, session, text, user)
        except Exception:
            logger.exception("feishu message could not be handed to the agent bot=%s", bot_id)
            _settle(session.id)
            if typing_reaction:
                client.remove_reaction(bot, message_id, typing_reaction)
            client.add_reaction(bot, message_id, client.REACTION_FAILURE)
            client.send_text(bot, chat_id, "消息没能交给智能体,请查看后端日志。")


# ---------------- 触发器认领了这条消息(ADR 0065)----------------


def _run_triggers(
    bot: FeishuBot,
    message,
    claimed: list[str],
    skipped: list[str],
    message_type: str,
    content_json: str,
) -> None:
    """触发器认领了这条消息:收附件 → 起运行 → 把回执发回群。

    附件下载排在这里而不是匹配之前 —— 只有**确定有人认**才值得去调飞书下载、落盘、探测、生成缩略图。
    附件取不回来时这一次不跑:素材就是入参,缺了起一次注定失败的运行没有意义。
    """
    asset_ids, _ = _ingest_attachments(bot, message.workspace_id, message.message_id, message_type, content_json)
    if not asset_ids and (_image_keys(message_type, content_json) or _file_attachment(message_type, content_json)[0]):
        client.send_text(bot, message.chat_id, "附件没能取回来(飞书资源下载失败),换一个或稍后再试。")
        return
    message = replace(message, asset_ids=tuple(asset_ids))
    with SessionLocal() as db:
        #: 去重、限流、起运行、落事件都在这一个事务里(领域不提交,入口提交 —— 见用例边界棘轮)。
        outcomes = trigger_dispatch.fire(db, message, list(claimed), skipped=list(skipped))
        db.commit()
    for outcome in outcomes:
        if outcome.receipt:
            #: 起跑成功的那一句回执:用户据此看出「这次是触发器起的」(ADR 0065 §3)。
            client.send_text(bot, outcome.chat_id or message.chat_id, outcome.receipt)


# ---------------- 一轮跑完:把结果送回飞书 ----------------

#: 每个会话里还在等回复的飞书消息(按到达顺序),收尾时摘掉它们的 Typing 反应。
#: 一轮对应一条:会话正忙时后来的消息排队,host 按先来后到一条一轮地跑。
_awaiting_replies: dict[str, list[tuple[str, str | None]]] = {}
_awaiting_lock = threading.Lock()


def _awaiting(session_id: str, message_id: str, reaction_id: str | None) -> None:
    with _awaiting_lock:
        _awaiting_replies.setdefault(session_id, []).append((message_id, reaction_id))


def _settle(session_id: str) -> tuple[str, str | None] | None:
    with _awaiting_lock:
        waiting = _awaiting_replies.get(session_id)
        if not waiting:
            return None
        first = waiting.pop(0)
        if not waiting:
            del _awaiting_replies[session_id]
        return first


def _route(db: Session, session: AgentSession) -> tuple[FeishuBot, str] | None:
    """external_key 形如 feishu:<bot_id>:<chat_id>;chat_id 里不含冒号。"""
    parts = (session.external_key or "").split(":", 2)
    if len(parts) != 3 or parts[0] != "feishu":
        return None
    bot = db.get(FeishuBot, parts[1])
    return (bot, parts[2]) if bot is not None else None


def deliver_turn(session_id: str) -> None:
    """host 一轮收尾后调用:把最后一条助手消息发回原飞书会话,摘掉 Typing,失败的轮次贴个叉。"""
    waiting = _settle(session_id)
    with SessionLocal() as db:
        session = db.get(AgentSession, session_id)
        if session is None:
            return
        route = _route(db, session)
        if route is None:
            return
        bot, chat_id = route
        reply = db.scalars(
            select(AgentMessage)
            .where(AgentMessage.session_id == session_id, AgentMessage.role == "assistant")
            .order_by(AgentMessage.created_at.desc())
            .limit(1)
        ).first()
        text = (reply.content if reply is not None else "") or "(空回复)"
        failed = reply is None or bool(reply.error)
        if waiting is not None:
            message_id, reaction_id = waiting
            # 收尾指示:摘掉 Typing;出错时换成 CrossMark 让用户一眼看到这轮失败了。
            if reaction_id:
                client.remove_reaction(bot, message_id, reaction_id)
            if failed:
                client.add_reaction(bot, message_id, client.REACTION_FAILURE)
        if not bot.enabled:
            return
        try:
            client.send_text(bot, chat_id, text)
        except client.FeishuError:
            logger.exception("feishu reply failed bot=%s chat=%s", bot.id, chat_id)


def system_note(db: Session, session: AgentSession) -> str:
    """飞书会话额外的系统提示:机器人的权限档,和「这是聊天软件,回复要短」。"""
    route = _route(db, session)
    capability = route[0].capability if route is not None else "editor"
    return (
        CAPABILITY_NOTES.get(capability, CAPABILITY_NOTES["editor"])
        + "\n你正通过飞书对话,回复保持简短(几句话内),不用 markdown 标题。"
    )


def _announce(db: Session, confirmation) -> None:
    from app.integrations.feishu.approvals import announce_confirmation

    announce_confirmation(db, confirmation)


origins.register(
    "feishu",
    origins.ExternalOrigin(system_note=system_note, turn_finished=deliver_turn, confirmation_opened=_announce),
)


# ---------------- 触发器起的那次运行跑完:把结果发回群(ADR 0065 §3)----------------


def deliver_trigger_run(db: Session, job: Job) -> None:
    """一次**触发器起的**运行落终态之后,把结果发回它来的那个群。

    登记在任务总线那条缝上(`jobs.register_settle_listener`),所以成功、失败、**取消**都走得到
    —— 取消不经过执行体的收尾代码,能在那一刻接住它的只有这里。

    哪个群靠事件行认:触发器上的 `bot_id` / `chat_id` 可能是空串(任意机器人 / 任意群),
    而这一次到底从哪来,只有写事件那一刻知道。
    """
    payload = job.payload or {}
    trigger_id = str(payload.get("trigger_id") or "")
    if not trigger_id:
        return  # 不是触发器起的 —— 绝大多数任务在这里路过
    trigger = db.get(WorkflowTrigger, trigger_id)
    if trigger is None or not trigger.reply_in_chat:
        return
    event = db.get(WorkflowTriggerEvent, str(payload.get("trigger_event_id") or ""))
    bot_id = (event.bot_id if event is not None else "") or trigger.bot_id
    chat_id = (event.chat_id if event is not None else "") or trigger.chat_id
    if not bot_id or not chat_id:
        return
    bot = db.get(FeishuBot, bot_id)
    if bot is None or not bot.enabled:
        return
    text = _run_result_text(db, job, trigger)
    if not text:
        return
    try:
        client.send_text(bot, chat_id, text)
    except client.FeishuError:
        logger.exception("feishu trigger result failed trigger=%s chat=%s", trigger.id, chat_id)


def _run_result_text(db: Session, job: Job, trigger: WorkflowTrigger) -> str:
    """这次运行交回群里的一句话。还没落终态(排队中 / 还在跑)时什么都不说。"""
    workflow = db.get(Workflow, trigger.workflow_id)
    name = workflow.name if workflow is not None else (trigger.name or trigger.id)
    if job.status == "failed":
        return t("triggerResult_failed", DEFAULT_LOCALE, workflow=name, reason=(job.error or "")[:500])
    if job.status == "cancelled":
        return t("triggerResult_cancelled", DEFAULT_LOCALE, workflow=name)
    if job.status != "succeeded":
        return ""
    body = _produced_text(job.result or {})
    if not body:
        return t("triggerResult_noOutput", DEFAULT_LOCALE, workflow=name)
    head = t("triggerResult_done", DEFAULT_LOCALE, workflow=name, trigger=trigger.name or trigger.id)
    return f"{head}\n\n{body}"


#: 回群里的正文最多多少字。群里要的是一句话,全文在 Mosael 的运行历史里(那边按需取全文)。
RESULT_TEXT_LIMIT = 1500


def _produced_text(result: dict) -> str:
    """这次运行交出来的文字:**输出节点声明的具名输出**优先(那是这张图的契约),
    没有就用上下文里各节点的 `text`(最后一个通常是最终答复)。

    注意这是**有界快照**(长文字在事件与结果里都截过,见 domain/workflows/run_outputs),
    所以这里不去承诺"发回群里的是全文"。
    """
    pieces: list[str] = []
    output = result.get("output")
    if isinstance(output, dict):
        pieces = [value for value in output.values() if isinstance(value, str) and value.strip()]
    if not pieces:
        context = result.get("context")
        if isinstance(context, dict):
            #: 取**最后**一个交回文字的节点:上下文按节点落定的先后排,最后那个通常就是终点的产出。
            #: (全部拼起来会把"开始节点交出的入参"和"终点的答复"一起发回群里,读起来像回声。)
            for node_out in context.values():
                text = node_out.get("text") if isinstance(node_out, dict) else None
                if isinstance(text, str) and text.strip():
                    pieces = [text]
    body = "\n\n".join(pieces).strip()
    if len(body) <= RESULT_TEXT_LIMIT:
        return body
    return body[:RESULT_TEXT_LIMIT] + "…"


register_settle_listener("feishu_workflow_triggers", deliver_trigger_run)


def notify_interrupted_chats(db: Session) -> int:
    """后端重启打断的飞书会话,把中断说明发回原聊天。

    会话状态已经被 reconcile_orphaned_agent_sessions 拨回 idle 并记了一条说明 —— 但那条
    只写进了库。桌面端看得到它,而在飞书里发消息的那个人只看到一片沉默,和"还在处理中"
    分辨不出来,于是一直等。开发时 --reload 尤其频繁,这就是"卡死"的另一半。
    """
    from app.domain.agent.host import interrupted_external_sessions, mark_interrupt_notified

    sent = 0
    for external_key, notice, message_id in interrupted_external_sessions(db, "feishu"):
        # external_key 形如 feishu:<bot_id>:<chat_id>;chat_id 里不含冒号。
        parts = external_key.split(":", 2)
        if len(parts) != 3 or parts[0] != "feishu":
            continue
        bot = db.get(FeishuBot, parts[1])
        if bot is None or not bot.enabled:
            # 机器人已删/已停用,这条通知**永远**发不出去 —— 也标掉,否则每次启动都白试一遍。
            mark_interrupt_notified(db, message_id)
            continue
        try:
            client.send_text(bot, parts[2], notice)
            sent += 1
        except Exception:  # noqa: BLE001 —— 通知失败不该拖垮启动
            # **发失败不标**:下次启动该再试 —— 失败多半是网络/令牌暂时不行,和"已送达"不同。
            logger.warning("feishu interrupt notice failed key=%s", external_key, exc_info=True)
        else:
            mark_interrupt_notified(db, message_id)
    return sent
