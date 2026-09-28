"""扫码一键创建机器人(OAuth device authorization grant,移植自前身项目):用户扫码授权,飞书替他建好
自建应用、配好权限和事件订阅,我们轮询拿到 app_id / app_secret 就存成一个机器人并连上。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from app.core.db import SessionLocal
from app.domain.feishu import bots
from app.integrations.feishu import client, connections

logger = logging.getLogger(__name__)

ONBOARD_ACCOUNTS_URLS = {"feishu": "https://accounts.feishu.cn", "lark": "https://accounts.larksuite.com"}
ONBOARD_REGISTRATION_PATH = "/oauth/v1/app/registration"

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
        raise client.FeishuError("feishuErr_qrUnsupported")
    res = _post_registration(
        base_url,
        {"action": "begin", "archetype": "PersonalAgent", "auth_method": "client_secret", "request_user_info": "open_id"},
    )
    device_code = res.get("device_code")
    if not device_code:
        raise client.FeishuError("feishuErr_noDeviceCode")
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
                bot = bots.create_bot(db, workspace_id=workspace_id, app_id=str(app_id), app_secret=str(app_secret))
                db.commit()
                bot_id = bot.id
            with _onboard_lock:
                _onboard_state[workspace_id] = {"phase": "done", "qr_url": None, "user_code": None, "error": None,
                                                "app_id": app_id, "_gen": gen}
            try:
                connections.start_connection(bot_id)
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
