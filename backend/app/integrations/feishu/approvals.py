"""工具确认卡:让批准在飞书里完成。

从飞书驱动智能体、却要切回桌面端点「同意」,这条链路只走了一半。确认卡直接发回发起的那个
飞书会话,批准/拒绝就地完成。卡片外观见 cards.py,那里也写了授权与「为什么不用存 message_id」。

## 工作流的「等人确认」也走这一条线

工作流跑到 `await_approval` 节点停下时要发的也是确认卡(标题正文由节点给,见
domain/workflows/approvals)。**同一个回调入口、同一条授权、同一张提交** —— `handle_card_action`
按动作名前缀把两种卡分流到各自的决定上,重复的只有"把 open_id 认成人"这一步(那正是它该被复用的)。

两条路的汇合点在**领域那一处**:`approvals.decide_and_wake`(CAS 写决定 + 提交后唤醒那次运行)。
飞书这一层只负责:认人、翻卡片、把领域异常说成 toast。

## 发出去之后还要收得回来

「等人确认」的卡发出去之后**还活着**(群里谁都能点)。所以这一层还负责两件后续:

- 发的时候把**投递结果**交回领域(`announce_run_approval` 返回 `Delivery`):卡片成了、退成文字
  成了、还是两层都没出去 —— 前两种都算发到了,后一种由领域在站内再喊一声;
- 这次等待结束(取消 / 超时)时把那张卡**收回成结果态**(`settle_run_approval`):就地换掉那条消息,
  换不掉就在同一个会话里补一条。两步都尽力 —— 取消本身已经落库了,这一步失败不该把它弄回去。

两件事的取舍写在 ADR 0069。
"""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.i18n import DEFAULT_LOCALE, render_message
from app.db.models import FeishuBot, Workflow, WorkflowRunApproval
from app.domain.feishu import bindings, routing
from app.domain.workflows.approvals import (
    DELIVERY_FAILED,
    DELIVERY_NOT_ATTEMPTED,
    DELIVERY_SENT,
    Delivery,
)
from app.integrations.feishu import client

logger = logging.getLogger(__name__)


def _feishu_origin(db: Session, session_id: str | None) -> tuple[FeishuBot, str] | None:
    """确认卡属于某次飞书会话时,返回(机器人, 会话 id)。

    `AgentSession.external_key` 里那串 `feishu:<bot_id>:<chat_id>` 的解析只有一处
    (`domain/feishu/routing.session_origin`)—— 工具确认卡和工作流的待批单读的是同一份。
    """
    return routing.session_origin(db, session_id)


def _full_summary(confirmation: Any) -> str:
    """按完整参数重新渲染,不用 `summary` 那个按列宽收口的快照 —— 飞书卡要给人读全文。"""
    key = str(getattr(confirmation, "summary_key", "") or "")
    if key:
        return render_message(key, DEFAULT_LOCALE, getattr(confirmation, "summary_params", None) or {})
    return str(getattr(confirmation, "summary", "") or getattr(confirmation, "tool", "") or "")


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
                    summary=_full_summary(confirmation),
                    requested_by=confirmation.requested_by,
                ),
            )
            return
        except client.FeishuError as exc:
            missing_capability = CARD_CAPABILITY_ERROR in str(exc)
            logger.warning("feishu card send failed, falling back to text: %s", exc)

        summary = _full_summary(confirmation) or confirmation.tool
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


def announce_run_approval(db: Session, approval: WorkflowRunApproval) -> Delivery:
    """把待批单发到飞书,**并交回投递结果**。**由工作流领域在组装根登记进来**(见 app.main._wire_seams
    与 domain/workflows/approvals.use_run_card_sender):领域层不认识飞书,飞书是调用领域的一方。

    发到哪**按节点上写的那三格**(`channel` / `bot` / `to`)解 —— 见 `route_for_approval`。
    不提交:调用方(领域那一处 after_commit 钩子开的会话)提交 —— 卡片发出去之后那三列路由信息
    才落库,而**真正要紧的检查点在那之前就已经提交了**(见 domain/workflows/approvals.announce)。

    三种结果分得开(见 domain/workflows/approvals 的模块说明):

    - `sent`:卡片成了,或者卡片失败之后退成的那段文字成了;
    - `not_attempted`:路由那一层就解不出收件人(写了「仅站内」/ 没有机器人 / 发起人没绑定)——
      **那是用户明说的选择或这次运行没有可发的去处,不是失败**;
    - `failed`:两层都没出去。原因交回领域那一边,由它写站内那条额外的提醒。
    """
    route = route_for_approval(db, approval)
    if route is None:
        #: **显式**说一句为什么不发飞书:节点上写了「仅站内」,或这次运行本来就没有可发的去处。
        #: 此前这里只有"返回 None"一种沉默 —— 而"照节点上写的没发"和"发不出去"是两件事。
        reason = route_reason(db, approval)
        logger.info("workflow approval %s not sent to feishu: %s", approval.id, reason)
        return Delivery(DELIVERY_NOT_ATTEMPTED, reason=reason)
    bot, receive_id, receive_type = route
    approval.feishu_bot_id = bot.id
    approval.feishu_receive_id = receive_id
    approval.feishu_receive_type = receive_type
    try:
        return send_approval_card(db, bot, receive_id, receive_type, approval)
    except Exception as exc:  # noqa: BLE001 —— 卡片和降级的文字都没出去:交给领域说给用户听
        logger.warning("workflow approval %s never reached feishu: %s", approval.id, exc)
        return Delivery(DELIVERY_FAILED, reason=str(exc).strip() or type(exc).__name__)


def approval_resolution(db: Session, approval: WorkflowRunApproval) -> routing.Resolution:
    """这张待批单按**节点上写的那三格**该发到飞书的哪里。

    节点配置从**这次运行钉住的那一版修订**里读(不是工作流当前那一版 —— 图可能已经改了),
    和 `_node_name` 同一个出处。目标解析本身在 `domain/feishu/routing`:「等人确认」和 4 个
    飞书能力节点共用它,所以同一个写法不会给出发给谁的两个答案。
    """
    from app.db.models import Job
    from app.domain.workflows import approvals as run_approvals

    config = run_approvals.node_config(db, approval)
    job = db.get(Job, approval.job_id)
    return routing.resolve(
        db,
        workspace_id=approval.workspace_id,
        #: `strict=False` **明说**:「等人确认」遇到发不出去可以退回站内(见 routing.channel_of)。
        #: 这一格没有缺省 —— 那条降级语义是这条路自己的,不该由别的调用方的默认值替它表态。
        channel=routing.channel_of(config, allowed=routing.APPROVAL_CHANNELS, fallback=routing.ORIGIN, strict=False),
        bot_id=routing.bot_id_of(config),
        to=routing.to_of(config),
        job=job,
    )


def route_reason(db: Session, approval: WorkflowRunApproval) -> str:
    """为什么不发飞书(或发到哪一档)。给日志用,也让"仅站内"这件事在记录里说得出来。"""
    return approval_resolution(db, approval).reason


def route_for_approval(db: Session, approval: WorkflowRunApproval) -> tuple[FeishuBot, str, str] | None:
    """这张待批单该发到飞书的哪里:(机器人, 收件 id, 收件 id 的类型);发不出去就是 None。

    解出来的地方见 `approval_resolution`(**节点上写的**那一档,不是自动猜的)。
    解不出来的几种(`none` 只站内 / 没有机器人 / 这次运行不是从飞书来的 / 收件人没绑)一律
    退回站内那条路 —— 一个门禁的用处是拦住"没人看着就往下走",不是拦住自己。
    """
    resolved = approval_resolution(db, approval)
    if resolved.target is None:
        return None
    target = resolved.target
    return target.bot, target.receive_id, target.receive_type


def send_approval_card(
    db: Session, bot: FeishuBot, receive_id: str, receive_type: str, approval: WorkflowRunApproval
) -> str:
    """把确认卡推出去,**返回那条消息的 id**(取消 / 超时要照它把卡收回)。

    失败分两层降级,和工具确认卡同一套:先退成一段文字;**两层都没出去就抛出去** ——
    调用方(`announce_run_approval`)据此把这一次记成 `failed`,而不是当成发过了。

    **"发一张卡 / 发一段文字"走的是和 4 个飞书能力节点同一份原语**(`integrations/feishu/gateway`
    那道缝后面的 transport,见 domain/feishu/gateway):两处各写一套的话,同一个"发飞书"会有两个
    实现,而它们迟早会在详情上分家(重试、token 刷新、地址)。卡片**长什么样**仍然是两回事:
    确认卡带按钮回调(`cards.approval_card`),节点那张卡只带一个链接。
    """
    from app.domain.feishu import gateway as domain_gateway
    from app.integrations.feishu import cards

    transport = domain_gateway.transport()
    hours = int(round((approval.timeout_seconds or 0) / 3600)) if approval.timeout_seconds else None
    workflow = db.get(Workflow, approval.workflow_id)
    card_failed = ""
    try:
        message_id = transport.send_card(
            bot, receive_id, receive_type,
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
        )
        return Delivery(DELIVERY_SENT, message_id=message_id)
    except client.FeishuError as exc:
        card_failed = str(exc)[:200]
        missing_capability = CARD_CAPABILITY_ERROR in card_failed
        #: **原因不能只写日志。** 日志会滚走(维护者原话:「由于日志的滚动 我已经无法看到」),
        #: 而这条原因要能事后查到、并且在设置页/待批卡上看见 —— 由调用方写进 `feishu_delivery_reason`。
        logger.warning("feishu approval card send failed, falling back to text: %s", exc)

    tail = f"\n\n(飞书内直接确认需要:{_CARD_SETUP_HINT})" if missing_capability else ""
    message_id = transport.send_text(
        bot, receive_id, receive_type,
        #: **不写"在飞书里回复"**:全仓没有任何一条路把飞书里的回复变成决定(只有卡片上的按钮是)。
        #: 那句话把人支去一个不存在的入口 —— 说清"到 Mosael 里处理"就够了。
        f"有一个工作流在等你确认:{approval.title}\n请到 Mosael 里处理。{tail}",
    )
    if missing_capability:
        #: 写进机器人状态,设置页那行小字会显示 —— 否则用户只在聊天里看到一次就过去了。
        #: 不提交:调用方那个事务提交(见 announce_run_approval)。
        bot_row = db.get(FeishuBot, bot.id)
        if bot_row is not None and CARD_CAPABILITY_ERROR not in (bot_row.status_detail or ""):
            bot_row.status_detail = f"交互卡片未开启({CARD_CAPABILITY_ERROR}):{_CARD_SETUP_HINT}"[:400]
    #: 卡片失败、退成文字时把**卡片那边的真实原因**一并交回:界面据此说清"为什么没有按钮",
    #: 而不是让用户以为"本来就是文字消息"。
    return Delivery(DELIVERY_SENT, message_id=message_id, reason=f"卡片发送失败,已改为文字:{card_failed}" if card_failed else "")


#: 这一次等待结束时补的那句话(取消 / 超时 / 到点提醒)。认不出的档位退到一句通用的话 —— 不抛。
#: `remind` **不是结果态**:这件事还在等,只是已经提醒过一次了 —— 写成"已经结束"会把群里的人
#: 支去一个还开着的门(见 domain/workflows/approvals.remind_feishu_card)。
_SETTLED_NOTICE = {
    "cancelled": "这次等待已经结束:已被取消,不用再点了。",
    "timeout": "这次等待已经结束:已超时,不用再点了。",
    "remind": "这件事还在等你确认,已经提醒过一次了 —— 决定权还在你手上。",
}


def settle_run_approval(db: Session, approval: WorkflowRunApproval, outcome: str) -> None:
    """这一次等待有了新说法(取消 / 超时 / 到点提醒):把飞书里那张卡**就地换成它**,别留在原地还能点。

    取消 / 超时是**结果态**(这件事结束了);`remind` 是"还在等,已提醒过一次"(见
    domain/workflows/approvals.remind_feishu_card)—— 同一套原语,只是卡上的话不一样。

    只在**确实发出去过**的时候调:领域那一边按 `feishu_message_id` 判过了(见
    domain/workflows/approvals.retire_feishu_card),这里再判一次 —— 这一步是被 after_commit
    排进来的,读到的那一行可能已经不是它当时看到的样子。

    两步都尽力,顺序也是有意的:

    1. **就地换掉**那条消息(消息 id 不变、按钮没了):群里的人一眼看出这件事结束了;
    2. 换不成(降级发出去的是纯文字消息,卡片换不了)就在**同一个会话**里补一条文字。

    **全程不抛**:调用方(领域)已经提交了那个结果,这一步失败只是"那张卡还留在那儿",
    不该把那个已经成立的结果弄回去。失败记日志 —— 想追一件事有没有说出去,看这里。
    """
    message_id = str(approval.feishu_message_id or "").strip()
    if not message_id:
        return
    bot = db.get(FeishuBot, approval.feishu_bot_id) if approval.feishu_bot_id else None
    if bot is None:
        logger.info("approval %s was sent by a bot that is gone; nothing to retire", approval.id)
        return
    from app.domain.feishu import gateway as domain_gateway
    from app.integrations.feishu import cards

    try:
        transport = domain_gateway.transport()
    except Exception:  # noqa: BLE001 —— 这一半没装上(组装根没登记):没有可收回的东西
        logger.info("feishu transport is not wired; nothing to retire for approval %s", approval.id)
        return
    if outcome == "remind":
        #: **提醒不换掉那张卡。** 门还开着 —— 卡上那两个按钮还得点得动,换成没有按钮的卡会让人
        #: 再也批不了。所以在同一个会话里补一句话就行(和上面"换不成"那条退路同一句话)。
        try:
            transport.send_text(
                bot, approval.feishu_receive_id, approval.feishu_receive_type, _SETTLED_NOTICE["remind"],
            )
        except Exception:  # noqa: BLE001 —— 见 docstring:补不上也只是日志,不影响"已提醒"
            logger.exception("feishu reminder notice failed approval=%s", approval.id)
        return
    try:
        transport.update_card(
            bot, message_id,
            cards.settled_approval_card(title=approval.title, decision=outcome, by="", note=""),
        )
        return
    except Exception as exc:  # noqa: BLE001 —— 见 docstring:换不掉就补一条
        logger.warning(
            "feishu approval card update failed approval=%s message=%s: %s", approval.id, message_id, exc
        )
    try:
        transport.send_text(
            bot, approval.feishu_receive_id, approval.feishu_receive_type,
            _SETTLED_NOTICE.get(outcome, "这次等待已经结束,不用再点了。"),
        )
    except Exception:  # noqa: BLE001 —— 见 docstring:补不上也只是日志
        logger.exception("feishu settled notice failed approval=%s", approval.id)


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


def _app_for_card(db: Session, bot_id: str, session_id: str | None) -> str:
    """点这张卡的人该按**哪个应用**的 open_id 认 —— 就是收到这次回调的那台机器人。

    open_id 按飞书应用隔离,所以绑定的键上有 bot 这一维;回调那一层没带机器人 id 时(测试直接调
    这一层、或更早的数据)退到这张卡自己挂着的飞书会话所属的那台(见 routing.session_origin)。
    """
    if bot_id:
        return bot_id
    origin = routing.session_origin(db, session_id)
    return origin[0].id if origin is not None else ""


def _handle_run_approval(open_id: str, action: str, value: dict[str, Any], bot_id: str = "") -> CardDecision:
    """工作流确认卡的按钮:授权按**点击者**走(和工具确认卡同一条路),决定落到领域那一处。

    授权这一关和工具确认卡刻意一致 —— 群里谁都看得见这张卡,但看得见不等于能批:
    必须已绑定 Mosael 账号、且此刻仍是该工作区成员(工作区**写权限**那一道闸在领域用例里,
    和应用内那条路是同一个,见 workflow_uc.decide_run_approval)。

    认人按**发出这张卡的那台机器人**(回调带过来的 `bot_id`,没有就用单子上存着的
    `feishu_bot_id`)—— 那张码 / 那个 open_id 属于哪个应用,认人才算得住。
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
        user = (
            bindings.resolve_sender(db, approval.workspace_id, bot_id or approval.feishu_bot_id, open_id)
            if open_id
            else None
        )
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


def handle_card_action(open_id: str, value: dict[str, Any], bot_id: str = "") -> CardDecision:
    """处理确认卡的按钮点击。

    授权按**点击者**走,和发消息完全同一条路径(bindings.resolve_sender):必须已绑定 Mosael
    账号、且此刻仍是该工作区成员。不是发起者也要过这关 —— 群里任何人都看得见这张卡,但看得见
    不等于能批。用 open_id 而不是 user_id:绑定表就是按 open_id 建的,两者混用会让明明绑过的人
    被拒(这是 Hermes 在飞书审批上踩过的坑)。

    **`bot_id` 是收到这次回调的那台机器人**(connections.dispatch 手里就有)。绑定按
    (工作区, 机器人, open_id)记 —— open_id 按飞书应用隔离,不带上它是拿别应用的 id 认人。
    没带时退到这张卡自己挂着的飞书会话所属的那台(见 `_app_for_card`);两者都没有就认不出人,
    回一句「请先绑定」而不是照旧认人。

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
    from app.integrations.feishu import cards, question_cards

    action = str(value.get("action") or "")
    confirmation_id = str(value.get("confirmation_id") or "")
    if action in question_cards.ACTIONS:
        return question_cards.handle_card_action(open_id, value, bot_id)
    #: **按动作名分流**:工具确认卡(改什么要人同意)和工作流的「等人确认」共用这一个回调入
    #: 口(见 connections.dispatch)。两件事的决定落在两张不同的单上,但"把 open_id 认成人、
    #: 把领域异常翻成 toast"这层是一样的 —— 所以是同一个入口,不是一个复制出来的入口。
    if action in (cards.ACTION_RUN_APPROVE, cards.ACTION_RUN_REJECT):
        return _handle_run_approval(open_id, action, value, bot_id)
    if action not in (cards.ACTION_APPROVE, cards.ACTION_REJECT) or not confirmation_id:
        return _toast("无法识别的操作")

    with SessionLocal() as db:
        confirmation = db.get(ToolConfirmation, confirmation_id)
        if confirmation is None:
            return _toast("这张确认卡已经不存在了")
        if confirmation.status != "pending":
            return _toast("这张确认卡已经处理过了")

        user = (
            bindings.resolve_sender(
                db, confirmation.workspace_id, _app_for_card(db, bot_id, confirmation.session_id), open_id,
            )
            if open_id
            else None
        )
        if user is None:
            return _toast("请先在 Mosael 的「飞书机器人」里绑定你的账号")

        summary, tool = _full_summary(confirmation), confirmation.tool
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
