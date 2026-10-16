"""工具确认卡:让批准在飞书里完成。

从飞书驱动智能体、却要切回桌面端点「同意」,这条链路只走了一半。确认卡直接发回发起的那个
飞书会话,批准/拒绝就地完成。卡片外观见 cards.py,那里也写了授权与「为什么不用存 message_id」。

## 工作流的「等人确认」也走这一条线

工作流跑到 `await_approval` 节点停下时要发的也是确认卡(标题正文由节点给,见
domain/workflows/approvals)。**同一个回调入口、同一条授权、同一张提交** —— `handle_card_action`
按动作名前缀把两种卡分流到各自的决定上,重复的只有"把 open_id 认成人"这一步(那正是它该被复用的)。

两条路的汇合点在**领域那一处**:`approvals.decide_and_wake`(CAS 写决定 + 提交后唤醒那次运行)。
飞书这一层只负责:认人、翻卡片、把领域异常说成 toast。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import AgentSession, FeishuBot, Workflow, WorkflowRunApproval
from app.domain.feishu import bindings
from app.integrations.feishu import client

logger = logging.getLogger(__name__)


def _feishu_origin(db: Session, session_id: str | None) -> tuple[FeishuBot, str] | None:
    """确认卡属于某次飞书会话时,返回(机器人, 会话 id)。

    路由信息全在 AgentSession.external_key 里(`feishu:<bot_id>:<chat_id>`,见
    get_or_create_external_session 的调用处),所以 ToolConfirmation 不需要为此加列。
    """
    if not session_id:
        return None
    session = db.get(AgentSession, session_id)
    if session is None or session.origin != "feishu" or not session.external_key:
        return None
    parts = session.external_key.split(":", 2)
    if len(parts) != 3 or parts[0] != "feishu":
        return None
    bot = db.get(FeishuBot, parts[1])
    return (bot, parts[2]) if bot is not None else None


#: 开发者后台没开交互卡片 / 没订阅 card.action.trigger 时,发卡片会撞上这个码。
#: **扫码一键创建的应用已经配好了这两项**,撞上它的基本只有手动建的应用。所以这条提示只在
#: 真撞上时出现,不做常驻横幅 —— 对一键创建的用户,常驻的那条是一句错的指令。
CARD_CAPABILITY_ERROR = "200340"

_CARD_SETUP_HINT = (
    "在飞书开发者后台为本应用:①「事件订阅」添加 card.action.trigger;"
    "②「应用功能 > 机器人」打开「交互卡片」;③ 重新发布应用。"
)


def announce_confirmation(db: Session, confirmation: Any) -> None:
    """把新建的确认卡推到它所属的飞书会话。

    推送失败一律降级、绝不抛:飞书那边出问题不该让确认本身建不出来。降级分两层 ——
    先退成纯文本(至少让飞书里的人知道「有东西等你确认」并给出原因),再不行就只剩桌面端的
    确认中心兜底,链路退化回「切回 App 批准」。
    """
    try:
        origin = _feishu_origin(db, confirmation.session_id)
        if origin is None:
            return
        bot, chat_id = origin
        from app.integrations.feishu import cards

        try:
            client.send_card(
                bot,
                chat_id,
                cards.confirmation_card(
                    confirmation_id=confirmation.id,
                    tool=confirmation.tool,
                    summary=confirmation.summary,
                    requested_by=confirmation.requested_by,
                ),
            )
            return
        except client.FeishuError as exc:
            missing_capability = CARD_CAPABILITY_ERROR in str(exc)
            logger.warning("feishu card send failed, falling back to text: %s", exc)

        summary = confirmation.summary or confirmation.tool
        tail = f"\n\n(飞书内直接批准需要:{_CARD_SETUP_HINT})" if missing_capability else ""
        client.send_text(bot, chat_id, f"有一个变更等待确认:{summary}\n请到 Mosael 里批准。{tail}")
        if missing_capability:
            # 写进机器人状态,设置页那行小字会显示 —— 否则用户只在聊天里看到一次就过去了。
            bot_row = db.get(FeishuBot, bot.id)
            if bot_row is not None and CARD_CAPABILITY_ERROR not in (bot_row.status_detail or ""):
                bot_row.status_detail = f"交互卡片未开启({CARD_CAPABILITY_ERROR}):{_CARD_SETUP_HINT}"[:400]
                db.commit()
    except Exception:  # noqa: BLE001 — 见 docstring
        logger.exception("feishu confirmation notice failed confirmation=%s", getattr(confirmation, "id", "?"))


class CardDecision(dict):
    """卡片回调的返回:要么 toast(只给点击者看、原卡不动),要么 card(就地替换原卡)。"""


def _toast(message: str) -> CardDecision:
    return CardDecision({"toast": {"type": "error", "content": message}})


# ---------------- 工作流「等人确认」:发卡、路由、收回调 ----------------


def announce_run_approval(db: Session, approval: WorkflowRunApproval) -> None:
    """把待批单发到飞书。**由工作流领域在组装根登记进来**(见 app.main._wire_seams 与
    domain/workflows/approvals.use_run_card_sender):领域层不认识飞书,飞书是调用领域的一方。

    不提交:调用方(领域那一处 after_commit 钩子开的会话)提交 —— 卡片发出去之后那三列路由信息
    才落库,而**真正要紧的检查点在那之前就已经提交了**(见 domain/workflows/approvals.announce)。
    """
    route = route_for_approval(db, approval)
    if route is None:
        return
    bot, receive_id, receive_type = route
    approval.feishu_bot_id = bot.id
    approval.feishu_receive_id = receive_id
    approval.feishu_receive_type = receive_type
    send_approval_card(db, bot, receive_id, receive_type, approval)


def route_for_approval(db: Session, approval: WorkflowRunApproval) -> tuple[FeishuBot, str, str] | None:
    """这张待批单该发到飞书的哪里:(机器人, 收件 id, 收件 id 的类型);发不出去就是 None。

    两条路,先近后远:

    1. **这一次运行来自飞书会话** —— 任务载荷里的回执指着一次 `origin="feishu"` 的智能体会话
       (`AgentSession.external_key` 是 `feishu:<bot_id>:<chat_id>`,和工具确认卡同一个取法),
       卡片发回那个群:谁在飞书里让这件事跑起来的,就在那儿批。
    2. **负责人绑过飞书** —— 运行不是从飞书来的,但发起这次运行的人在这个工作区绑了账号:
       卡片当私聊发给他(`receive_id_type=open_id`)。这就是需求里"工作区绑了飞书机器人"那一半。

    两条都不成立(这很常见:本地用、没接飞书)就返回 None —— 上层照旧发站内通知、这次运行照旧在等。
    """
    from app.db.models import Job
    from app.domain.workflows import approvals as run_approvals

    job = db.get(Job, approval.job_id)
    receipt = (job.payload or {}).get("receipt") if job is not None else None
    if isinstance(receipt, dict):
        origin = _feishu_origin(db, str(receipt.get("session_id") or ""))
        if origin is not None:
            bot, chat_id = origin
            return bot, chat_id, "chat_id"
    fallback = run_approvals.bot_for_user(db, approval.workspace_id, job.created_by if job is not None else None)
    if fallback is None:
        return None
    bot, open_id = fallback
    return bot, open_id, "open_id"


def send_approval_card(
    db: Session, bot: FeishuBot, receive_id: str, receive_type: str, approval: WorkflowRunApproval
) -> None:
    """把确认卡推出去。失败分两层降级,和工具确认卡同一套:先退成一段文字,再不行就只剩站内那条路。"""
    from app.integrations.feishu import cards

    hours = int(round((approval.timeout_seconds or 0) / 3600)) if approval.timeout_seconds else None
    workflow = db.get(Workflow, approval.workflow_id)
    try:
        client.send_card(
            bot, receive_id,
            cards.approval_card(
                approval_id=approval.id,
                title=approval.title,
                body=approval.body,
                workflow=workflow.name if workflow is not None else approval.workflow_id,
                node=approval.node_name or approval.node_id,
                approve_label=approval.approve_label,
                reject_label=approval.reject_label,
                allow_note=bool(approval.allow_note),
                timeout_hours=hours,
            ),
            receive_id_type=receive_type,
        )
        return
    except client.FeishuError as exc:
        missing_capability = CARD_CAPABILITY_ERROR in str(exc)
        logger.warning("feishu approval card send failed, falling back to text: %s", exc)

    tail = f"\n\n(飞书内直接确认需要:{_CARD_SETUP_HINT})" if missing_capability else ""
    client.send_text(
        bot, receive_id,
        f"有一个工作流在等你确认:{approval.title}\n请到 Mosael 里处理,或在飞书里回复。{tail}",
        receive_id_type=receive_type,
    )
    if missing_capability:
        #: 写进机器人状态,设置页那行小字会显示 —— 否则用户只在聊天里看到一次就过去了。
        #: 不提交:调用方那个事务提交(见 announce_run_approval)。
        bot_row = db.get(FeishuBot, bot.id)
        if bot_row is not None and CARD_CAPABILITY_ERROR not in (bot_row.status_detail or ""):
            bot_row.status_detail = f"交互卡片未开启({CARD_CAPABILITY_ERROR}):{_CARD_SETUP_HINT}"[:400]


def _note_from(value: dict[str, Any]) -> str:
    """卡片上那格备注。**飞书把表单值放在哪儿有几种写法**,能读到就读,读不到就是空 ——
    备注丢了是可接受的退化,批不动不是(见 cards.approval_card 的说明)。"""
    direct = value.get("note")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()
    raw = value.get("form_value")
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            raw = None
    if isinstance(raw, dict):
        note = raw.get("note")
        if isinstance(note, str):
            return note.strip()
    return ""


def _handle_run_approval(open_id: str, action: str, value: dict[str, Any]) -> CardDecision:
    """工作流确认卡的按钮:授权按**点击者**走(和工具确认卡同一条路),决定落到领域那一处。

    授权这一关和工具确认卡刻意一致 —— 群里谁都看得见这张卡,但看得见不等于能批:
    必须已绑定 Mosael 账号、且此刻仍是该工作区成员(工作区**写权限**那一道闸在领域用例里,
    和应用内那条路是同一个,见 workflow_uc.decide_run_approval)。
    """
    from app.domain.permissions import PermissionDenied
    from app.integrations.feishu import cards

    approval_id = str(value.get("approval_id") or "")
    if not approval_id:
        return _toast("无法识别的操作")
    decision = "approved" if action == cards.ACTION_RUN_APPROVE else "rejected"
    with SessionLocal() as db:
        approval = db.get(WorkflowRunApproval, approval_id)
        if approval is None:
            return _toast("这次等待已经不在了")
        if approval.status != "pending":
            #: 已经决定过(另一条路先到):卡跟着改成结果态,别让人以为没点上。
            return CardDecision({"card": {"type": "raw", "data": cards.settled_approval_card(
                title=approval.title, decision=approval.decision or approval.status,
                by=approval.decided_by_name, note=approval.note,
            )}})
        user = bindings.resolve_sender(db, approval.workspace_id, open_id) if open_id else None
        if user is None:
            return _toast("请先在 Mosael 的「飞书机器人」里绑定你的账号")
        note = _note_from(value)
        try:
            #: **和 HTTP 路由同一个用例**(workflow_uc.decide_run_approval):工作区写权限那一道闸、
            #: CAS 落决定、提交之后唤醒那次运行,全都在那一处。这里只负责把 open_id 认成人、
            #: 把领域异常翻成 toast。
            from app.domain.workflows import use_cases as workflow_uc

            won = workflow_uc.decide_run_approval(
                db, user, approval, decision=decision, note=note, via="feishu",
            )
            db.commit()  # 卡片回调是入口:领域函数不提交
        except PermissionDenied:
            return _toast("你在 Mosael 里没有这个工作区的编辑权限")
        except Exception:  # noqa: BLE001 —— 含权限不足与执行失败
            logger.exception("feishu workflow approval failed approval=%s", approval_id)
            return _toast("处理失败,请到 Mosael 里查看")
        if not won:
            return _toast("这张卡已经处理过了")
        return CardDecision({"card": {"type": "raw", "data": cards.settled_approval_card(
            title=approval.title, decision=decision, by=user.display_name or user.username, note=note,
        )}})


def handle_card_action(open_id: str, value: dict[str, Any]) -> CardDecision:
    """处理确认卡的按钮点击。

    授权按**点击者**走,和发消息完全同一条路径(_resolve_sender):必须已绑定 Mosael
    账号、且此刻仍是该工作区成员。不是发起者也要过这关 —— 群里任何人都看得见这张卡,但看得见
    不等于能批。用 open_id 而不是 user_id:绑定表就是按 open_id 建的,两者混用会让明明绑过的人
    被拒(这是 Hermes 在飞书审批上踩过的坑)。

    批准走的是与 HTTP 路由同一个 authorize_and_approve,且按点击者校验:卡是他批的,这次执行
    就记在他头上。

    失败一律回 toast:原卡保持可点,好让真正有权限的人接手。
    """
    from app.db.models import ToolConfirmation
    from app.domain.agent.confirmations import (
        ConfirmationError,
        authorize_and_approve,
        authorize_and_reject,
    )
    from app.integrations.feishu import cards

    action = str(value.get("action") or "")
    confirmation_id = str(value.get("confirmation_id") or "")
    #: **按动作名分流**:工具确认卡(改什么要人同意)和工作流的「等人确认」共用这一个回调入
    #: 口(见 connections.dispatch)。两件事的决定落在两张不同的单上,但"把 open_id 认成人、
    #: 把领域异常翻成 toast"这层是一样的 —— 所以是同一个入口,不是一个复制出来的入口。
    if action in (cards.ACTION_RUN_APPROVE, cards.ACTION_RUN_REJECT):
        return _handle_run_approval(open_id, action, value)
    if action not in (cards.ACTION_APPROVE, cards.ACTION_REJECT) or not confirmation_id:
        return _toast("无法识别的操作")

    with SessionLocal() as db:
        confirmation = db.get(ToolConfirmation, confirmation_id)
        if confirmation is None:
            return _toast("这张确认卡已经不存在了")
        if confirmation.status != "pending":
            return _toast("这张确认卡已经处理过了")

        user = bindings.resolve_sender(db, confirmation.workspace_id, open_id) if open_id else None
        if user is None:
            return _toast("请先在 Mosael 的「飞书机器人」里绑定你的账号")

        summary, tool = confirmation.summary, confirmation.tool
        try:
            # 校验与执行都在 authorize_and_*(和 HTTP 路由共用同一份)。这一层只负责:
            # 把 open_id 认成人、把领域异常翻成 toast。
            if action == cards.ACTION_APPROVE:
                authorize_and_approve(db, user, confirmation)
                decision = "approved"
            else:
                authorize_and_reject(db, user, confirmation)
                decision = "rejected"
            db.commit()  # 卡片回调是入口:领域函数不提交
        except ConfirmationError as exc:
            return _toast(str(exc))
        except Exception:  # noqa: BLE001 — 含权限不足(code 节点)与执行失败
            logger.exception("feishu card decision failed confirmation=%s", confirmation_id)
            return _toast("处理失败,请到 Mosael 里查看")

        return CardDecision(
            {
                "card": {
                    "type": "raw",
                    "data": cards.settled_card(
                        summary=summary, tool=tool, decision=decision, by=user.username
                    ),
                }
            }
        )
