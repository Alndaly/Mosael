from __future__ import annotations

import json
import logging
import re
import secrets
import subprocess
import sys
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.agent.adapters import AdapterError, run_turn
from app.ai.agent.host import (
    SYSTEM_PROMPT_TEMPLATE,
    append_message,
    get_or_create_external_session,
    resolve_chat_provider,
)
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import mint_service_session
from app.core.child_process import popen_text
from app.db.models import (
    AgentSession,
    FeishuBindCode,
    FeishuBinding,
    FeishuBot,
    User,
    WorkspaceMember,
    now,
)

"""
飞书(Lark)双向接入,移植自旧项目的长连接方案:lark_oapi.ws.Client 长连接收消息
(无需公网 webhook),tenant_access_token 发消息。每个机器人一个独立子进程
(SDK 的事件循环是模块级共享的,进程才是安全隔离边界)。收到的消息路由到
Agent 宿主层的外部会话(external_key = feishu:bot:chat),回复发回原会话。
"""

logger = logging.getLogger(__name__)

API_BASE = "https://open.feishu.cn/open-apis"
TOKEN_URL = f"{API_BASE}/auth/v3/tenant_access_token/internal"
SEND_URL = f"{API_BASE}/im/v1/messages"
ONBOARD_ACCOUNTS_URLS = {"feishu": "https://accounts.feishu.cn", "lark": "https://accounts.larksuite.com"}
ONBOARD_REGISTRATION_PATH = "/oauth/v1/app/registration"

MENTION_RE = re.compile(r"^(@_user_\d+\s*)+")


class FeishuError(RuntimeError):
    pass


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
        raise FeishuError(f"获取 tenant_access_token 失败: {data.get('msg') or data.get('code')}")
    token = str(data["tenant_access_token"])
    with _token_lock:
        _token_cache[bot.id] = (token, time.time() + float(data.get("expire", 7200)))
    return token


def _call_api(bot: FeishuBot, method: str, url: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
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
    data = _call_api(
        bot,
        "POST",
        f"{SEND_URL}?receive_id_type=chat_id",
        {"receive_id": chat_id, "msg_type": "text", "content": json.dumps({"text": text})},
    )
    if data.get("code") != 0:
        raise FeishuError(f"飞书发消息失败: {data.get('msg') or data.get('code')}")


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
        data = _call_api(
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
        data = _call_api(bot, "DELETE", f"{SEND_URL}/{message_id}/reactions/{reaction_id}")
        return data.get("code") == 0
    except Exception:  # noqa: BLE001
        logger.warning("feishu remove_reaction %s on %s failed", reaction_id, message_id, exc_info=True)
        return False


# --- inbound message handling ------------------------------------------------

def extract_text(content_json: str) -> str:
    """从消息 content 里取纯文本。text 与 post(富文本)都收 —— 用户带格式粘贴一段话,
    飞书发过来的就是 post,而它对用户来说和普通文字没有任何区别。"""
    try:
        parsed = json.loads(content_json or "{}")
    except ValueError:
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
        raise FeishuError(f"下载飞书资源失败({response.status_code})")
    return response.content


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
    "editor": "本会话为编辑档:可以提交时间线修改与生成的确认卡,等待用户在 Open Studio 中批准。",
    "full": "本会话为完整档:可使用全部工具,变更仍需用户在 Open Studio 中批准确认卡。",
}


#: 能读进来的消息类型。其余类型不是丢掉,而是回一句说明 —— 见 _describe_unsupported。
SUPPORTED_MESSAGE_TYPES = frozenset({"text", "post", "image"})


def _image_keys(message_type: str, content_json: str) -> list[str]:
    """消息里的图片 file_key。image 消息一张;post(富文本)可以内嵌多张。"""
    try:
        parsed = json.loads(content_json or "{}")
    except ValueError:
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


def _ingest_images(bot: FeishuBot, workspace_id: str, message_id: str, keys: list[str]) -> list[str]:
    """把图片下载进素材库,返回素材 id。

    **走素材库而不是直接塞给模型**:桌面端的回形针也是这么做的(上传成素材 → 在提示里引用),
    智能体分析图片靠的是 analyze_asset 这个工具。两条入口落到同一个地方,飞书发来的图片
    此后在素材库里也找得到、能复用,而不是只在那一轮对话里存在过。
    """
    from app.domain.assets.importer import import_binary_asset

    asset_ids: list[str] = []
    for index, key in enumerate(keys[:MAX_INBOUND_IMAGES]):
        try:
            data = download_message_resource(bot, message_id, key, "image")
        except Exception:  # noqa: BLE001 —— 一张下不来不该让整条消息失败
            logger.warning("feishu image download failed key=%s", key, exc_info=True)
            continue
        with SessionLocal() as db:
            asset = import_binary_asset(
                db,
                workspace_id=workspace_id,
                project_id=None,
                data=data,
                original=f"feishu-{message_id[-8:]}-{index + 1}.jpg",
                content_type="image/jpeg",
                source="feishu",
            )
            asset_ids.append(asset.id)
    return asset_ids


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
    return f"我暂时看不了{what}。可以发文字或图片给我,或者把文件先传进 Open Studio 的素材库再让我处理。"


def handle_incoming(
    bot_id: str,
    chat_id: str,
    message_id: str,
    sender_open_id: str = "",
    *,
    message_type: str = "text",
    content_json: str = "",
) -> None:
    """Runs inside the worker process: route one Feishu message through the agent host,
    acting as the SENDER's bound account (not a blanket owner). Unbound senders are refused."""
    if seen_recently(message_id):
        return
    text = extract_text(content_json)
    image_keys = _image_keys(message_type, content_json)
    with SessionLocal() as db:
        bot = db.get(FeishuBot, bot_id)
        if bot is None or not bot.enabled:
            return
        if message_type not in SUPPORTED_MESSAGE_TYPES:
            # 说一句,而不是沉默。用户发过来什么都得到回应,哪怕是"我看不了这个"。
            send_text(bot, chat_id, _describe_unsupported(message_type))
            return
        if not text and not image_keys:
            return
        # Identify the human behind the message. No open_id → can't attribute → refuse.
        user = _resolve_sender(db, bot.workspace_id, sender_open_id) if sender_open_id else None
        if user is None:
            # An unbound sender may be redeeming a one-time bind code they got in-app.
            redeemed = _redeem_bind_code(db, bot.workspace_id, sender_open_id, text) if sender_open_id else None
            if redeemed is not None:
                send_text(bot, chat_id, f"绑定成功,你好 {redeemed.username}!之后直接对我说话即可。")
            else:
                send_text(
                    bot,
                    chat_id,
                    "你还没有绑定 Open Studio 账号,无法使用本机器人。请在 Open Studio『设置 → 飞书机器人』生成绑定码,"
                    "然后把绑定码直接发给我完成绑定。",
                )
            return
        session = get_or_create_external_session(
            db,
            workspace_id=bot.workspace_id,
            external_key=f"feishu:{bot.id}:{chat_id}",
            title=f"飞书 · {bot.name}",
        )
        if session.status == "running":
            send_text(bot, chat_id, "上一条还在处理中,稍等片刻再发~")
            return
        # 图片下载要几秒(下载 + 探测 + 缩略图),不该占着数据库会话;而 bot 是纯配置,
        # 出了 session 只用它的 id/app_id/app_secret 调 REST,detached 也够用。
        db.expunge(bot)
        images_workspace = bot.workspace_id

    if image_keys:
        asset_ids = _ingest_images(bot, images_workspace, message_id, image_keys)
        if not asset_ids:
            send_text(bot, chat_id, "图片没能取回来(飞书资源下载失败),换一张或稍后再试。")
            return
        # 图片先入素材库,再把素材 id 写进提示 —— 智能体靠 analyze_asset 看图,和桌面端
        # 回形针走的是同一条路(上传成素材 → 在提示里引用),不是给飞书单开一套。
        note = (
            f"[用户发来 {len(asset_ids)} 张图片,已存入素材库,素材 id:{'、'.join(asset_ids)}。"
            "需要看图就用 analyze_asset。]"
        )
        text = f"{text}\n{note}" if text else note

    with SessionLocal() as db:
        session = get_or_create_external_session(
            db,
            workspace_id=images_workspace,
            external_key=f"feishu:{bot.id}:{chat_id}",
            title=f"飞书 · {bot.name}",
        )
        user = _resolve_sender(db, images_workspace, sender_open_id)
        if user is None:
            return
        append_message(db, session.id, role="user", content=text)
        session.status = "running"
        # 铸造即提交,连同上面的消息与状态。带上会话:确认卡的归属由令牌决定(见 core/security),
        # 飞书这条链路同样靠它把卡送回**发起它的那个飞书会话**(announce_confirmation 按 session 找回)。
        token = mint_service_session(db, user.id, agent_session_id=session.id)
        session_id, adapter, workspace_id, capability = (
            session.id, session.adapter, bot.workspace_id, bot.capability
        )
        adapter_state = session.adapter_state  # pi 多轮记忆:与 AI Studio 同一套回环
        # 供应商解析必须在这里做(与 AI Studio 同一助手):裸调 run_turn 不带 provider,
        # pi 适配器会直接报「未配置可用的 AI 供应商」,哪怕设置里已配好。
        try:
            # 行动人是**发消息的那个绑定成员**,不是会话的主人 —— 飞书会话是机器人建的
            # (一个群一个,owner_user_id 为空),而群里每个人各用各的钥匙、各自的默认模型。
            # 与上面 mint_service_session 用的是同一个人。
            provider_dict, agent_model, _profile = resolve_chat_provider(
                db, session.provider_profile_id, session.model or "", user_id=user.id
            )
        except AdapterError as exc:
            provider_dict, agent_model = None, None
            provider_error = str(exc)
        else:
            provider_error = None

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        workspace_id=workspace_id,
    )
    system_prompt += "\n" + CAPABILITY_NOTES.get(capability, CAPABILITY_NOTES["editor"])
    system_prompt += "\n你正通过飞书对话,回复保持简短(几句话内),不用 markdown 标题。"
    api_base = f"http://{settings.backend_host}:{settings.backend_port}"

    # 「码字中」指示:给用户那条消息贴 Typing 反应,飞书客户端渲染成动画输入指示。
    # bot 对象来自已关闭的 session,但 id/app_id/app_secret 均已加载,REST 调用够用。
    typing_reaction = add_reaction(bot, message_id, REACTION_TYPING)

    reply_text = ""
    error: str | None = None
    new_adapter_session: str | None = None
    new_adapter_state: object | None = None
    try:
        if provider_error:
            raise AdapterError(provider_error)
        result = run_turn(
            adapter,
            prompt=text,
            system_prompt=system_prompt,
            api_base=api_base,
            token=token,
            provider=provider_dict,
            model=agent_model,
            workspace_id=workspace_id,
            adapter_state=adapter_state,
            session_key=session_id,
        )
        reply_text = result.text or "(空回复)"
        new_adapter_state = result.adapter_state
    except AdapterError as exc:
        # 适配器错误本就是给人看的中文(没配供应商/缺模型/sidecar 未构建)——
        # 原样带给用户,笼统的「稍后再试」只会让人反复重试同一个配置问题。
        reply_text = f"智能体执行失败:{exc}"
        error = str(exc)[:800]
    except Exception as exc:  # the worker thread must never die silently
        logger.exception("feishu turn crashed bot=%s", bot_id)
        reply_text = "智能体执行异常,请查看后端日志。"
        error = str(exc)[:800]

    with SessionLocal() as db:
        session = db.get(AgentSession, session_id)
        if session is not None:
            append_message(db, session.id, role="assistant", content=reply_text, error=error)
            if new_adapter_state is not None:
                session.adapter_state = new_adapter_state
            session.status = "idle"
            session.updated_at = now()
            db.commit()
        bot = db.get(FeishuBot, bot_id)
        if bot is not None:
            # 收尾指示:摘掉 Typing;出错时换成 CrossMark 让用户一眼看到这轮失败了。
            if typing_reaction:
                remove_reaction(bot, message_id, typing_reaction)
            if error:
                add_reaction(bot, message_id, REACTION_FAILURE)
            try:
                send_text(bot, chat_id, reply_text)
            except FeishuError:
                logger.exception("feishu reply failed bot=%s chat=%s", bot_id, chat_id)


def notify_interrupted_chats(db: Session) -> int:
    """后端重启打断的飞书会话,把中断说明发回原聊天。

    会话状态已经被 reconcile_orphaned_agent_sessions 拨回 idle 并记了一条说明 —— 但那条
    只写进了库。桌面端看得到它,而在飞书里发消息的那个人只看到一片沉默,和"还在处理中"
    分辨不出来,于是一直等。开发时 --reload 尤其频繁,这就是"卡死"的另一半。
    """
    from app.ai.agent.host import interrupted_external_sessions

    sent = 0
    for external_key, notice in interrupted_external_sessions(db, "feishu"):
        # external_key 形如 feishu:<bot_id>:<chat_id>;chat_id 里不含冒号。
        parts = external_key.split(":", 2)
        if len(parts) != 3 or parts[0] != "feishu":
            continue
        bot = db.get(FeishuBot, parts[1])
        if bot is None or not bot.enabled:
            continue
        try:
            send_text(bot, parts[2], notice)
            sent += 1
        except Exception:  # noqa: BLE001 —— 通知失败不该拖垮启动
            logger.warning("feishu interrupt notice failed key=%s", external_key, exc_info=True)
    return sent


def _is_member(db: Session, workspace_id: str, user_id: str) -> bool:
    return db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id}) is not None


def _resolve_sender(db: Session, workspace_id: str, open_id: str) -> User | None:
    """The Open Studio account bound to this Feishu sender — only if still a workspace member."""
    binding = db.get(FeishuBinding, {"workspace_id": workspace_id, "open_id": open_id})
    if binding is None or not _is_member(db, workspace_id, binding.user_id):
        return None
    return db.get(User, binding.user_id)


def _redeem_bind_code(db: Session, workspace_id: str, open_id: str, text: str) -> User | None:
    """If `text` is a live bind code for this workspace, bind open_id → its issuer and consume it."""
    code = (text or "").strip().upper()
    if not (4 <= len(code) <= 16):
        return None
    row = db.get(FeishuBindCode, {"workspace_id": workspace_id, "code": code})
    if row is None or row.expires_at < now() or not _is_member(db, workspace_id, row.user_id):
        return None
    db.merge(FeishuBinding(workspace_id=workspace_id, open_id=open_id, user_id=row.user_id))
    db.delete(row)
    db.commit()
    return db.get(User, row.user_id)


def issue_bind_code(db: Session, workspace_id: str, user_id: str) -> tuple[str, datetime]:
    """Member self-issues a one-time code (10-min TTL) to redeem from Feishu."""
    code = secrets.token_hex(3).upper()  # 6 hex chars
    expires = now() + timedelta(minutes=10)
    db.merge(FeishuBindCode(workspace_id=workspace_id, code=code, user_id=user_id, expires_at=expires))
    db.commit()
    return code, expires


def list_bindings(db: Session, workspace_id: str) -> list[tuple[str, User]]:
    rows = db.execute(
        select(FeishuBinding.open_id, User)
        .join(User, User.id == FeishuBinding.user_id)
        .where(FeishuBinding.workspace_id == workspace_id)
    ).all()
    return [(open_id, user) for open_id, user in rows]


def remove_binding(db: Session, workspace_id: str, open_id: str) -> None:
    binding = db.get(FeishuBinding, {"workspace_id": workspace_id, "open_id": open_id})
    if binding is not None:
        db.delete(binding)
        db.commit()


# --- connection lifecycle (one child process per bot) ------------------------

_processes: dict[str, subprocess.Popen] = {}
_process_lock = threading.Lock()


def write_status(bot_id: str, status: str, detail: str = "") -> None:
    with SessionLocal() as db:
        bot = db.get(FeishuBot, bot_id)
        if bot is not None:
            bot.status = status
            bot.status_detail = detail[:400]
            db.commit()


def start_connection(bot_id: str) -> None:
    backend_dir = Path(__file__).resolve().parents[3]
    python = backend_dir / ".venv" / "bin" / "python"
    with _process_lock:
        existing = _processes.get(bot_id)
        if existing is not None and existing.poll() is None:
            return
        write_status(bot_id, "connecting")
        process = popen_text(
            [str(python if python.exists() else sys.executable), "-m", "app.integrations.feishu.worker", bot_id],
            cwd=backend_dir,
        )
        _processes[bot_id] = process


def stop_connection(bot_id: str) -> None:
    with _process_lock:
        process = _processes.pop(bot_id, None)
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    write_status(bot_id, "offline")


def autostart_enabled_bots() -> None:
    with SessionLocal() as db:
        bots = db.scalars(select(FeishuBot).where(FeishuBot.enabled.is_(True))).all()
        for bot in bots:
            bot.status = "offline"
        db.commit()
        bot_ids = [bot.id for bot in bots]
    for bot_id in bot_ids:
        try:
            start_connection(bot_id)
        except Exception:
            logger.exception("feishu autostart failed bot=%s", bot_id)


def stop_all_connections() -> None:
    with _process_lock:
        ids = list(_processes)
    for bot_id in ids:
        stop_connection(bot_id)


# --- 扫码一键创建 (device authorization grant, ported from the predecessor project) --------

_onboard_lock = threading.Lock()
_onboard_state: dict[str, dict[str, Any]] = {}  # workspace_id -> {phase, qr_url, user_code, error, app_id, _gen}


def _post_registration(base_url: str, body: dict[str, str]) -> dict[str, Any]:
    with httpx.Client(timeout=10.0) as client:
        response = client.post(f"{base_url}{ONBOARD_REGISTRATION_PATH}", data=body)
    try:
        return response.json()
    except ValueError:
        return {}


def begin_onboarding(workspace_id: str, domain: str = "feishu") -> dict[str, Any]:
    base_url = ONBOARD_ACCOUNTS_URLS.get(domain, ONBOARD_ACCOUNTS_URLS["feishu"])
    init_res = _post_registration(base_url, {"action": "init"})
    if "client_secret" not in (init_res.get("supported_auth_methods") or []):
        raise FeishuError("当前环境不支持扫码创建,请手动填写 App ID / App Secret。")
    res = _post_registration(
        base_url,
        {"action": "begin", "archetype": "PersonalAgent", "auth_method": "client_secret", "request_user_info": "open_id"},
    )
    device_code = res.get("device_code")
    if not device_code:
        raise FeishuError("飞书未返回 device_code,扫码创建暂不可用,请手动创建应用。")
    state = {
        "phase": "waiting_scan",
        "qr_url": res.get("verification_uri_complete") or "",
        "user_code": res.get("user_code") or "",
        "error": None,
        "app_id": None,
    }
    with _onboard_lock:
        gen = int((_onboard_state.get(workspace_id) or {}).get("_gen") or 0) + 1
        _onboard_state[workspace_id] = {**state, "_gen": gen}
    threading.Thread(
        target=_poll_onboarding,
        args=(workspace_id, device_code, domain, float(res.get("interval") or 5), float(res.get("expire_in") or 600), gen),
        daemon=True,
    ).start()
    return state


def _poll_onboarding(workspace_id: str, device_code: str, domain: str, interval: float, expire_in: float, gen: int) -> None:
    deadline = time.time() + expire_in
    current_domain = domain
    while time.time() < deadline:
        with _onboard_lock:
            if int((_onboard_state.get(workspace_id) or {}).get("_gen") or 0) != gen:
                return  # superseded by a newer scan
        base_url = ONBOARD_ACCOUNTS_URLS.get(current_domain, ONBOARD_ACCOUNTS_URLS["feishu"])
        try:
            res = _post_registration(base_url, {"action": "poll", "device_code": device_code, "tp": "ob_app"})
        except Exception:
            time.sleep(interval)
            continue
        if ((res.get("user_info") or {}).get("tenant_brand")) == "lark" and current_domain != "lark":
            current_domain = "lark"
        app_id, app_secret = res.get("client_id"), res.get("client_secret")
        if app_id and app_secret:
            with SessionLocal() as db:
                bot = FeishuBot(workspace_id=workspace_id, app_id=str(app_id), app_secret=str(app_secret))
                db.add(bot)
                db.commit()
                bot_id = bot.id
            with _onboard_lock:
                _onboard_state[workspace_id] = {"phase": "done", "qr_url": None, "user_code": None, "error": None,
                                                "app_id": app_id, "_gen": gen}
            try:
                start_connection(bot_id)
            except Exception:
                logger.exception("feishu onboarding saved bot but connection failed ws=%s", workspace_id)
            return
        error = res.get("error") or ""
        if error in {"access_denied", "expired_token"}:
            with _onboard_lock:
                _onboard_state[workspace_id] = {"phase": "error", "qr_url": None, "user_code": None, "app_id": None,
                                                "error": "用户拒绝了授权" if error == "access_denied" else "二维码已过期",
                                                "_gen": gen}
            return
        time.sleep(interval)
    with _onboard_lock:
        _onboard_state[workspace_id] = {"phase": "error", "qr_url": None, "user_code": None, "app_id": None,
                                        "error": "扫码超时,请重试。", "_gen": gen}


def onboarding_status(workspace_id: str) -> dict[str, Any]:
    with _onboard_lock:
        state = dict(_onboard_state.get(workspace_id) or {"phase": "idle"})
    state.pop("_gen", None)
    return state


# --- 工具确认卡:让批准在飞书里完成 -------------------------------------------
#
# 从飞书驱动智能体、却要切回桌面端点「同意」,这条链路只走了一半。确认卡直接发回发起的那个
# 飞书会话,批准/拒绝就地完成。卡片外观见 cards.py,那里也写了授权与「为什么不用存 message_id」。


def send_card(bot: FeishuBot, chat_id: str, card: dict[str, Any]) -> None:
    data = _call_api(
        bot,
        "POST",
        f"{SEND_URL}?receive_id_type=chat_id",
        {"receive_id": chat_id, "msg_type": "interactive", "content": json.dumps(card, ensure_ascii=False)},
    )
    if data.get("code") != 0:
        raise FeishuError(f"飞书发卡片失败: {data.get('msg') or data.get('code')}")


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
            send_card(
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
        except FeishuError as exc:
            missing_capability = CARD_CAPABILITY_ERROR in str(exc)
            logger.warning("feishu card send failed, falling back to text: %s", exc)

        summary = confirmation.summary or confirmation.tool
        tail = f"\n\n(飞书内直接批准需要:{_CARD_SETUP_HINT})" if missing_capability else ""
        send_text(bot, chat_id, f"有一个变更等待确认:{summary}\n请到 Open Studio 里批准。{tail}")
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

    授权按**点击者**走,和发消息完全同一条路径(_resolve_sender):必须已绑定 Open Studio
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

        user = _resolve_sender(db, confirmation.workspace_id, open_id) if open_id else None
        if user is None:
            return _toast("请先在 Open Studio 的「飞书机器人」里绑定你的账号")

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
            return _toast("处理失败,请到 Open Studio 里查看")

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
