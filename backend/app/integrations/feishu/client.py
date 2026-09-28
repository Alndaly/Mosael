"""飞书开放平台的 REST 调用:租户令牌(按机器人缓存、提前两分钟刷新)、发文字 / 卡片、
表情反应(飞书的「对方正在输入」)、取回消息里的图片与文件。只懂飞书,不懂 Mosael 的业务。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any

import httpx

from app.core.i18n import LocalizedError
from app.db.models import FeishuBot

logger = logging.getLogger(__name__)

API_BASE = "https://open.feishu.cn/open-apis"
TOKEN_URL = f"{API_BASE}/auth/v3/tenant_access_token/internal"
SEND_URL = f"{API_BASE}/im/v1/messages"


class FeishuError(LocalizedError, RuntimeError):
    """飞书这一侧没做成。带文案 key(`feishuErr_*`);飞书自己回的 msg / code 放进 `detail`。"""


# --- tenant token cache (per bot, refreshed with safety margin) -------------

_token_lock = threading.Lock()
_token_cache: dict[str, tuple[str, float]] = {}


def get_tenant_access_token(bot: FeishuBot, force: bool = False) -> str:
    with _token_lock:
        cached = _token_cache.get(bot.id)
        if cached and not force and cached[1] > time.time() + 120:
            return cached[0]
    response = httpx.post(TOKEN_URL, json={"app_id": bot.app_id, "app_secret": bot.app_secret}, timeout=15.0)
    data = response.json()
    if data.get("code") != 0:
        raise FeishuError("feishuErr_token", detail=data.get("msg") or data.get("code"))
    token = str(data["tenant_access_token"])
    with _token_lock:
        _token_cache[bot.id] = (token, time.time() + float(data.get("expire", 7200)))
    return token


def call_api(bot: FeishuBot, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    def _call(token: str) -> dict[str, Any]:
        with httpx.Client(timeout=15.0) as client:
            response = client.request(method, url, headers={"Authorization": f"Bearer {token}"}, json=body)
            response.raise_for_status()
            return response.json()

    data = _call(get_tenant_access_token(bot))
    if data.get("code") == 99991663:  # token expired mid-flight
        data = _call(get_tenant_access_token(bot, force=True))
    return data


def send_text(bot: FeishuBot, chat_id: str, text: str) -> None:
    data = call_api(
        bot,
        "POST",
        f"{SEND_URL}?receive_id_type=chat_id",
        {"receive_id": chat_id, "msg_type": "text", "content": json.dumps({"text": text})},
    )
    if data.get("code") != 0:
        raise FeishuError("feishuErr_sendText", detail=data.get("msg") or data.get("code"))


def send_card(bot: FeishuBot, chat_id: str, card: dict[str, Any]) -> None:
    data = call_api(
        bot,
        "POST",
        f"{SEND_URL}?receive_id_type=chat_id",
        {"receive_id": chat_id, "msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False)},
    )
    if data.get("code") != 0:
        raise FeishuError("feishuErr_sendCard", detail=data.get("msg") or data.get("code"))


# --- 反应(reaction)= 飞书的「对方正在输入」(前身项目同款) ----------------
#
# 飞书没有 Slack/iMessage 那种原生输入指示器;给用户发来的那条消息加 emoji_type="Typing"
# 的反应,客户端会渲染成动画输入指示 —— 处理完删掉,失败换 "CrossMark"。全程 best-effort:
# 缺个小徽章纯属装饰问题,绝不能反过来弄坏回复链路。

REACTION_TYPING = "Typing"
REACTION_FAILURE = "CrossMark"


def add_reaction(bot: FeishuBot, message_id: str, emoji_type: str) -> str | None:
    """Best-effort; returns the reaction_id needed to remove it later, or None."""
    try:
        data = call_api(
            bot, "POST", f"{SEND_URL}/{message_id}/reactions", {"reaction_type": {"emoji_type": emoji_type}}
        )
        if data.get("code") != 0:
            logger.warning("feishu add_reaction %s on %s rejected: %s", emoji_type, message_id, data)
            return None
        return (data.get("data") or {}).get("reaction_id")
    except Exception:  # noqa: BLE001
        logger.warning("feishu add_reaction %s on %s failed", emoji_type, message_id, exc_info=True)
        return None


def remove_reaction(bot: FeishuBot, message_id: str, reaction_id: str) -> bool:
    """Best-effort; never raises."""
    try:
        data = call_api(bot, "DELETE", f"{SEND_URL}/{message_id}/reactions/{reaction_id}")
        return data.get("code") == 0
    except Exception:  # noqa: BLE001
        logger.warning("feishu remove_reaction %s on %s failed", reaction_id, message_id, exc_info=True)
        return False


def download_message_resource(bot: FeishuBot, message_id: str, file_key: str, kind: str) -> bytes:
    """把消息里的图片/文件取回来。走 tenant token,和其它 API 调用同一条路。"""

    def _fetch(token: str) -> httpx.Response:
        with httpx.Client(timeout=60.0) as client:
            return client.get(
                f"{API_BASE}/im/v1/messages/{message_id}/resources/{file_key}",
                params={"type": kind},
                headers={"Authorization": f"Bearer {token}"},
            )

    response = _fetch(get_tenant_access_token(bot))
    if response.status_code == 401:  # token 半路过期
        response = _fetch(get_tenant_access_token(bot, force=True))
    if response.status_code != 200:
        raise FeishuError("feishuErr_download", status=response.status_code)
    return response.content
