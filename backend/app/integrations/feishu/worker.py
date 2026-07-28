"""子进程入口:一个机器人一条飞书长连接。

``python -m app.integrations.feishu.worker <bot_id>`` — 由 service.start_connection
拉起。独立进程是 lark_oapi SDK 的硬约束:它的 ws 客户端共享模块级事件循环,同一进程
跑多条连接会互相污染。子进程复用同一份代码与 SQLite,直接调 service.handle_incoming。
"""

from __future__ import annotations

import logging
import sys
import threading
import time
import uuid

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

CONNECTING_GRACE_SECONDS = 8.0


def main(bot_id: str) -> None:
    import lark_oapi as lark

    from app.core.db import SessionLocal
    from app.db.models import FeishuBot
    from app.integrations.feishu import service

    with SessionLocal() as db:
        bot = db.get(FeishuBot, bot_id)
        if bot is None:
            logger.error("feishu worker: bot %s not found", bot_id)
            sys.exit(2)
        app_id, app_secret = bot.app_id, bot.app_secret

    service.write_status(bot_id, "connecting")

    def _mark_online_after_grace() -> None:
        time.sleep(CONNECTING_GRACE_SECONDS)
        with SessionLocal() as db:
            row = db.get(FeishuBot, bot_id)
            if row is not None and row.status == "connecting":
                row.status = "online"
                db.commit()

    threading.Thread(target=_mark_online_after_grace, daemon=True).start()

    def _on_message(data) -> None:
        """SDK event-loop thread — filter fast, hand slow work to a thread."""
        try:
            event = getattr(data, "event", None)
            if event is None:
                return
            sender = getattr(event, "sender", None)
            if ((getattr(sender, "sender_type", "") or "").lower()) == "bot":
                return  # never answer bots (including ourselves) — loop protection
            sender_id = getattr(sender, "sender_id", None)
            open_id = getattr(sender_id, "open_id", "") or ""  # who sent it → maps to an Open Studio member
            message = getattr(event, "message", None)
            if message is None or getattr(message, "message_type", None) != "text":
                return
            message_id = getattr(message, "message_id", "") or uuid.uuid4().hex
            chat_id = getattr(message, "chat_id", None)
            text = service.extract_text(getattr(message, "content", "") or "")
            if not chat_id or not text:
                return
            threading.Thread(
                target=service.handle_incoming, args=(bot_id, chat_id, text, message_id, open_id), daemon=True
            ).start()
        except Exception:
            logger.exception("feishu event handling failed bot=%s", bot_id)

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_on_message)
        .register_p2_im_message_message_read_v1(lambda data: None)  # read receipts: harmless, silence them
        .build()
    )
    client = lark.ws.Client(app_id, app_secret, event_handler=handler, log_level=lark.LogLevel.INFO)
    try:
        client.start()  # blocking for the lifetime of the connection
    except Exception as exc:
        logger.exception("feishu worker exited bot=%s", bot_id)
        service.write_status(bot_id, "error", str(exc))
        raise


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python -m app.integrations.feishu.worker <bot_id>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
