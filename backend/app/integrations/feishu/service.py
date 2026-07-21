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
from app.ai.agent.host import SYSTEM_PROMPT_TEMPLATE, get_or_create_external_session, append_message
from app.domain.agent.prompt_skills import skills_index_for_prompt
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import mint_service_session
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

TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
SEND_URL = "https://open.feishu.cn/open-apis/im/v1/messages"
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


# --- inbound message handling ------------------------------------------------

def extract_text(content_json: str) -> str:
    try:
        parsed = json.loads(content_json or "{}")
    except ValueError:
        return ""
    return MENTION_RE.sub("", str(parsed.get("text") or "")).strip()


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
    "editor": "本会话为编辑档:可以提交时间线修改与生成的确认卡,等待用户在 Mibu 中批准。",
    "full": "本会话为完整档:可使用全部工具,变更仍需用户在 Mibu 中批准确认卡。",
}


def handle_incoming(bot_id: str, chat_id: str, text: str, message_id: str, sender_open_id: str = "") -> None:
    """Runs inside the worker process: route one Feishu message through the agent host,
    acting as the SENDER's bound account (not a blanket owner). Unbound senders are refused."""
    if seen_recently(message_id):
        return
    with SessionLocal() as db:
        bot = db.get(FeishuBot, bot_id)
        if bot is None or not bot.enabled:
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
                    "你还没有绑定 Mibu 账号,无法使用本机器人。请在 Mibu『设置 → 飞书机器人』生成绑定码,"
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
        append_message(db, session.id, role="user", content=text)
        session.status = "running"
        token = mint_service_session(db, user.id)  # 铸造即提交,连同上面的消息与状态
        session_id, adapter, adapter_session_id, workspace_id, capability = (
            session.id, session.adapter, session.adapter_session_id, bot.workspace_id, bot.capability
        )

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        workspace_id=workspace_id,
        skills_index=skills_index_for_prompt() or "(暂无技能)",
    )
    system_prompt += "\n" + CAPABILITY_NOTES.get(capability, CAPABILITY_NOTES["editor"])
    system_prompt += "\n你正通过飞书对话,回复保持简短(几句话内),不用 markdown 标题。"
    api_base = f"http://{settings.backend_host}:{settings.backend_port}"

    reply_text = ""
    error: str | None = None
    new_adapter_session: str | None = None
    try:
        result = run_turn(
            adapter,
            prompt=text,
            system_prompt=system_prompt,
            api_base=api_base,
            token=token,
            adapter_session_id=adapter_session_id,
        )
        reply_text = result.text or "(空回复)"
        new_adapter_session = result.adapter_session_id
    except AdapterError as exc:
        reply_text = "智能体执行失败,请稍后再试。"
        error = str(exc)[:800]
    except Exception as exc:  # the worker thread must never die silently
        logger.exception("feishu turn crashed bot=%s", bot_id)
        reply_text = "智能体执行异常。"
        error = str(exc)[:800]

    with SessionLocal() as db:
        session = db.get(AgentSession, session_id)
        if session is not None:
            append_message(db, session.id, role="assistant", content=reply_text, error=error)
            if new_adapter_session:
                session.adapter_session_id = new_adapter_session
            session.status = "idle"
            session.updated_at = now()
            db.commit()
        bot = db.get(FeishuBot, bot_id)
        if bot is not None:
            try:
                send_text(bot, chat_id, reply_text)
            except FeishuError:
                logger.exception("feishu reply failed bot=%s chat=%s", bot_id, chat_id)


def _is_member(db: Session, workspace_id: str, user_id: str) -> bool:
    return db.get(WorkspaceMember, {"workspace_id": workspace_id, "user_id": user_id}) is not None


def _resolve_sender(db: Session, workspace_id: str, open_id: str) -> User | None:
    """The Mibu account bound to this Feishu sender — only if still a workspace member."""
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
        process = subprocess.Popen(
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


# --- 扫码一键创建 (device authorization grant, ported from mibu-video) --------

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
