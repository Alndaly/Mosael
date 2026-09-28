"""工具确认卡:让批准在飞书里完成。

从飞书驱动智能体、却要切回桌面端点「同意」,这条链路只走了一半。确认卡直接发回发起的那个
飞书会话,批准/拒绝就地完成。卡片外观见 cards.py,那里也写了授权与「为什么不用存 message_id」。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.db.models import AgentSession, FeishuBot
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
