"""子进程入口:一个机器人一条飞书长连接,**只转发事件**。

``python -m app.integrations.feishu.worker <bot_id>`` — 由 connections.start_connection 拉起。
独立进程是 lark_oapi SDK 的硬约束:它的 ws 客户端共享模块级事件循环,同一进程跑多条连接会互相污染。

它不碰数据库、不要主密钥、不跑智能体 —— 那些都在主进程,和桌面端同一条路。此前这里直接调
inbound.handle_incoming:子进程自己开库、自己解密 app_secret、自己跑一整轮 turn,于是主密钥得
交下来,turn 也有了第二份实现。现在协议是按行的 JSON(见 PROTOCOL):

    stdin  第一行          {"app_id": ..., "app_secret": ...}      主进程交来的连接凭据
    stdin  之后每行         {"id": n, "result": {...}}              卡片回调的答复
    stdout ``@@mosael `` + {"event": "message", ...}                收到一条消息
                           {"event": "card", "id": n, ...}         确认卡按钮被点了,等答复
                           {"event": "status", "status": ..., "detail": ...}

stdout 上别的行(SDK 自己打的日志)原样当日志处理,不当协议。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
import uuid
from typing import Any

logger = logging.getLogger(__name__)

PROTOCOL = "@@mosael "
CONNECTING_GRACE_SECONDS = 8.0
#: 飞书要求卡片回调 3 秒内答复;留一点余量给来回的管道。
CARD_REPLY_SECONDS = 2.5

_write_lock = threading.Lock()


def emit(event: dict[str, Any]) -> None:
    with _write_lock:
        sys.stdout.write(PROTOCOL + json.dumps(event, ensure_ascii=False) + "\n")
        sys.stdout.flush()


class CardReplies:
    """卡片回调要**同步**返回(飞书拿返回值更新卡片 / 弹 toast),而决定在主进程里做。
    每次点击发一条带 id 的事件,在这里等主进程按 id 答复。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next = 0
        self._waiting: dict[int, tuple[threading.Event, list[dict]]] = {}

    def ask(self, open_id: str, value: dict[str, Any], timeout: float = CARD_REPLY_SECONDS) -> dict:
        with self._lock:
            self._next += 1
            request_id = self._next
            done, box = threading.Event(), []
            self._waiting[request_id] = (done, box)
        emit({"event": "card", "id": request_id, "open_id": open_id, "value": value})
        try:
            if done.wait(timeout) and box:
                return box[0]
            return {"toast": {"type": "info", "content": "正在处理,稍后请到 Mosael 里查看结果"}}
        finally:
            with self._lock:
                self._waiting.pop(request_id, None)

    def answer(self, request_id: int, result: dict) -> None:
        with self._lock:
            waiting = self._waiting.get(request_id)
        if waiting is not None:
            waiting[1].append(result)
            waiting[0].set()

    def pump(self, lines) -> None:
        """读主进程的答复,直到管道关闭。"""
        for line in lines:
            try:
                reply = json.loads(line)
                self.answer(int(reply["id"]), dict(reply["result"]))
            except (ValueError, KeyError, TypeError):
                logger.warning("feishu worker: unreadable reply line")


def follow_parent(replies: CardReplies, lines, exit_process=os._exit) -> None:
    """读主进程的答复;**管道一关就退出**。

    stdin 是主进程攥着的那一头:它关了,就是主进程没了(崩了、被杀了、测试跑完没收尾)。此前这里读到
    EOF 就安静地停下,而 `client.start()` 那条长连接照跑 —— 孤儿进程一直占着飞书连接,主进程重启后
    同一个机器人就有了两条连接,每条消息收两遍;测试里一次留下几十个,把内存吃光。
    """
    replies.pump(lines)
    logger.info("feishu worker: parent closed the pipe, exiting")
    exit_process(0)


def message_event(data: Any) -> dict[str, Any] | None:
    """SDK 的消息事件 → 协议事件。机器人(包括自己)发的一律不转 —— 防回环。"""
    event = getattr(data, "event", None)
    if event is None:
        return None
    sender = getattr(event, "sender", None)
    if ((getattr(sender, "sender_type", "") or "").lower()) == "bot":
        return None
    sender_id = getattr(sender, "sender_id", None)
    message = getattr(event, "message", None)
    if message is None:
        return None
    chat_id = getattr(message, "chat_id", None)
    if not chat_id:
        return None
    # 消息类型交给 inbound 判断,这里**不过滤**:以前这里是 `if message_type != "text": return`,
    # 发张图片过来用户永远等不到回复。静默丢弃和"正在处理"长得一模一样。
    return {
        "event": "message",
        "chat_id": chat_id,
        "message_id": getattr(message, "message_id", "") or uuid.uuid4().hex,
        "open_id": getattr(sender_id, "open_id", "") or "",
        "message_type": (getattr(message, "message_type", "") or "").lower(),
        "content": getattr(message, "content", "") or "",
    }


def card_action(data: Any) -> tuple[str, dict[str, Any]]:
    """SDK 的卡片回调 → (点击者 open_id, 按钮 value)。用 open_id:绑定表按它建。"""
    event = getattr(data, "event", None)
    operator = getattr(event, "operator", None)
    action = getattr(event, "action", None)
    value = getattr(action, "value", None) or {}
    if isinstance(value, str):
        value = json.loads(value)
    return getattr(operator, "open_id", "") or "", dict(value)


def main(bot_id: str) -> None:
    import lark_oapi as lark

    credentials = json.loads(sys.stdin.readline() or "{}")
    app_id, app_secret = credentials.get("app_id", ""), credentials.get("app_secret", "")
    if not app_id or not app_secret:
        logger.error("feishu worker: no credentials for bot %s", bot_id)
        sys.exit(2)

    replies = CardReplies()
    threading.Thread(target=follow_parent, args=(replies, sys.stdin), daemon=True).start()

    def _mark_online_after_grace() -> None:
        time.sleep(CONNECTING_GRACE_SECONDS)
        emit({"event": "status", "status": "online"})

    threading.Thread(target=_mark_online_after_grace, daemon=True).start()

    def _on_message(data) -> None:
        try:
            event = message_event(data)
            if event is not None:
                emit(event)
        except Exception:
            logger.exception("feishu event relay failed bot=%s", bot_id)

    def _on_card_action(data):
        try:
            open_id, value = card_action(data)
            return replies.ask(open_id, value)
        except Exception:
            logger.exception("feishu card action failed bot=%s", bot_id)
            return {"toast": {"type": "error", "content": "处理失败,请到 Mosael 里查看"}}

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(_on_message)
        .register_p2_im_message_message_read_v1(lambda data: None)  # read receipts: harmless, silence them
        .register_p2_card_action_trigger(_on_card_action)
        .build()
    )
    client = lark.ws.Client(app_id, app_secret, event_handler=handler, log_level=lark.LogLevel.INFO)
    try:
        client.start()  # blocking for the lifetime of the connection
    except Exception as exc:
        logger.exception("feishu worker exited bot=%s", bot_id)
        emit({"event": "status", "status": "error", "detail": str(exc)})
        raise


if __name__ == "__main__":
    #: 只在作为子进程跑时配日志:主进程 import 这个模块(拿 PROTOCOL)不该顺手改了它的根日志器。
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("usage: python -m app.integrations.feishu.worker <bot_id>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1])
