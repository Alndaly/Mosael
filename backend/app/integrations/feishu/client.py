"""飞书开放平台的 REST 调用:租户令牌(按机器人缓存、提前两分钟刷新)、发文字 / 卡片、
表情反应(飞书的「对方正在输入」)、取回消息里的图片与文件、列出机器人所在的群。只懂飞书,不懂 Mosael 的业务。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

from app.core.http_retry import RetryingClient
from app.core.i18n import LocalizedError
from app.db.models import FeishuBot

logger = logging.getLogger(__name__)

API_BASE = "https://open.feishu.cn/open-apis"
TOKEN_URL = f"{API_BASE}/auth/v3/tenant_access_token/internal"
SEND_URL = f"{API_BASE}/im/v1/messages"
#: 机器人所在的那个群列表(`im/v1/chats`):节点上「发到某个群」和「列出机器人所在的群」都读它。
CHATS_URL = f"{API_BASE}/im/v1/chats"
#: 一页最多要几个群(飞书自己的上限)。
CHATS_PAGE_SIZE = 100


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
    with RetryingClient(timeout=15.0, max_retries=0) as client:
        response = client.post(TOKEN_URL, json={"app_id": bot.app_id, "app_secret": bot.app_secret})
    data = response.json()
    if data.get("code") != 0:
        raise FeishuError("feishuErr_token", detail=data.get("msg") or data.get("code"))
    token = str(data["tenant_access_token"])
    with _token_lock:
        _token_cache[bot.id] = (token, time.time() + float(data.get("expire", 7200)))
    return token


def call_api(bot: FeishuBot, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    def _call(token: str) -> dict[str, Any]:
        with RetryingClient(timeout=15.0, max_retries=0) as client:
            response = client.request(method, url, headers={"Authorization": f"Bearer {token}"}, json=body)
            response.raise_for_status()
            return response.json()

    data = _call(get_tenant_access_token(bot))
    if data.get("code") == 99991663:  # token expired mid-flight
        data = _call(get_tenant_access_token(bot, force=True))
    return data


def _message_id(data: dict[str, Any]) -> str:
    """发出去那条消息的 id(`om_…`)。飞书没给就是空串 —— 调用方照旧按"发出去了"算。"""
    return str((data.get("data") or {}).get("message_id") or "")


def send_text(bot: FeishuBot, chat_id: str, text: str, *, receive_id_type: str = "chat_id") -> str:
    """发一条文字,返回它的 message_id。`receive_id_type` 是 `chat_id`(会话)或 `open_id`(私聊某个人)。"""
    data = call_api(
        bot,
        "POST",
        f"{SEND_URL}?receive_id_type={receive_id_type}",
        {"receive_id": chat_id, "msg_type": "text", "content": json.dumps({"text": text})},
    )
    if data.get("code") != 0:
        raise FeishuError("feishuErr_sendText", detail=data.get("msg") or data.get("code"))
    return _message_id(data)


def send_card(bot: FeishuBot, chat_id: str, card: dict[str, Any], *, receive_id_type: str = "chat_id") -> str:
    """发一张交互卡片,返回它的 message_id。`receive_id_type` 是 `chat_id`(会话,默认)或 `open_id`(私聊某个人)——
    工作流的确认卡两条路都要:这一轮**来自飞书会话**就发回那个群,不是的话发给负责人本人。"""
    data = call_api(
        bot,
        "POST",
        f"{SEND_URL}?receive_id_type={receive_id_type}",
        {"receive_id": chat_id, "msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False)},
    )
    if data.get("code") != 0:
        raise FeishuError("feishuErr_sendCard", detail=data.get("msg") or data.get("code"))
    return _message_id(data)


def update_card(bot: FeishuBot, message_id: str, card: dict[str, Any]) -> None:
    """**就地换掉**一张已经发出去的交互卡片(`PATCH im/v1/messages/:message_id`)。

    飞书只让改"这张应用自己发的、而且那条消息是交互卡片"的消息 —— 降级发出去的那种纯文字消息
    改不了,调用方据此再补一条(见 integrations/feishu/approvals.settle_run_approval)。
    """
    data = call_api(bot, "PATCH", f"{SEND_URL}/{message_id}", {"content": json.dumps(card, ensure_ascii=False)})
    if data.get("code") != 0:
        raise FeishuError("feishuErr_updateCard", detail=data.get("msg") or data.get("code"))


def list_chats(bot: FeishuBot, *, limit: int = 200) -> list[dict[str, str]]:
    """这个机器人所在的群:`[{"id": "oc_…", "name": "…"}]`,按飞书给的顺序。

    飞书按 `page_token` 分页(`has_more` / `page_token`),这里跟到底 —— 但当心"跟到底"也可能是
    几千个群:调用方给 `limit` 划上界,到这里就停(不再要下一页)。
    """
    found: list[dict[str, str]] = []
    cap = max(1, int(limit))
    page_token = ""
    while True:
        query = f"?page_size={CHATS_PAGE_SIZE}" + (f"&page_token={quote(page_token)}" if page_token else "")
        data = call_api(bot, "GET", f"{CHATS_URL}{query}")
        if data.get("code") != 0:
            raise FeishuError("feishuErr_listChats", detail=data.get("msg") or data.get("code"))
        page = data.get("data") or {}
        for item in page.get("items") or []:
            if not isinstance(item, dict):
                continue
            chat_id = str(item.get("chat_id") or "").strip()
            if chat_id:
                found.append({"id": chat_id, "name": str(item.get("name") or "").strip() or chat_id})
        page_token = str(page.get("page_token") or "").strip()
        if len(found) >= cap or not page.get("has_more") or not page_token:
            return found[:cap]


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
        return add_reaction_strict(bot, message_id, emoji_type) or None
    except Exception:  # noqa: BLE001
        logger.warning("feishu add_reaction %s on %s failed", emoji_type, message_id, exc_info=True)
        return None


def add_reaction_strict(bot: FeishuBot, message_id: str, emoji_type: str) -> str:
    """加一个表情,**加不上就抛**。返回 reaction_id。

    「回个表情」那个节点要的是这一份:`add_reaction` 的"尽力而为"服务的是输入指示器那种点缀
    (坏了也不能反过来弄坏回复链路),而一个专门用来加表情的节点加不上时**必须说**。
    """
    data = call_api(
        bot, "POST", f"{SEND_URL}/{message_id}/reactions", {"reaction_type": {"emoji_type": emoji_type}}
    )
    if data.get("code") != 0:
        raise FeishuError("feishuErr_reaction", detail=data.get("msg") or data.get("code"))
    return str((data.get("data") or {}).get("reaction_id") or "")


def remove_reaction(bot: FeishuBot, message_id: str, reaction_id: str) -> bool:
    """Best-effort; never raises."""
    try:
        data = call_api(bot, "DELETE", f"{SEND_URL}/{message_id}/reactions/{reaction_id}")
        return data.get("code") == 0
    except Exception:  # noqa: BLE001
        logger.warning("feishu remove_reaction %s on %s failed", reaction_id, message_id, exc_info=True)
        return False


@dataclass(frozen=True)
class DownloadedResource:
    """从消息里取回来的一份资源:字节、它叫什么、飞书说它是什么类型。

    名字来自响应的 `Content-Disposition`(飞书会把原始文件名放在那儿)。取不回来时按 `file_key`
    与类型兜一个 —— **素材库按名字/类型认种类**(见 media/probe.guess_kind):没有名字也没有类型
    的字节会被当成视频去探测,然后被拒收。
    """

    data: bytes
    filename: str
    content_type: str


def _resource_name(disposition: str, file_key: str, kind: str) -> str:
    """`Content-Disposition` 里的文件名;没有就按 file_key 与类型兜一个认得出的名字。"""
    for marker in ("filename*=UTF-8''", 'filename="', "filename="):
        at = disposition.find(marker)
        if at < 0:
            continue
        tail = disposition[at + len(marker):]
        name = tail.split(";")[0].strip().strip('"').strip()
        if name:
            return name
    suffix = ".jpg" if kind == "image" else ""
    return f"feishu-{file_key[-8:]}{suffix}"


def download_message_resource_named(bot: FeishuBot, message_id: str, file_key: str, kind: str) -> DownloadedResource:
    """把消息里的图片/文件取回来,**连它的名字和类型一起**。走 tenant token,和其它 API 调用同一条路。"""

    def _fetch(token: str) -> httpx.Response:
        with RetryingClient(timeout=60.0, max_retries=0) as client:
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
    disposition = response.headers.get("content-disposition", "")
    return DownloadedResource(
        data=response.content,
        filename=_resource_name(disposition, file_key, kind),
        content_type=(response.headers.get("content-type") or "").split(";")[0].strip(),
    )


def download_message_resource(bot: FeishuBot, message_id: str, file_key: str, kind: str) -> bytes:
    """只要字节的那条老路(入站那条链路在用):它就是上面那一份 `.data`。"""
    return download_message_resource_named(bot, message_id, file_key, kind).data
