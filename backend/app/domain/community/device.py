"""连社区账号:设备授权(RFC 8628,ADR 0026 §3)。

1. `start`:向社区要一个设备码(`POST /auth/device/code`),把 `user_code` 和验证地址交给界面 ——
   界面用系统浏览器打开那个地址,用户在网页上登录、确认「允许这台 Mosael 访问你的社区账号」;
2. `poll`:界面每隔一会儿问一次,这里**按服务端给的 `interval` 节流**才真的去问社区
   (`POST /auth/device/token`)。太早的那几次直接回「还在等」,一次网络请求都不发;
3. 对方回 `slow_down` → 间隔加 5 秒(RFC 8628 §3.5);`428 authorization_pending` → 接着等;
   `410` / 过了 `expires_in` → 这个码作废,界面让人重来;拿到令牌 → 落盘,连上了。

待完成的那个流程在进程内存里(`_flows`,见 docs/PROCESS_STATE.md):设备码能换令牌,不落盘;
后端重启了就重新点一次「连接」。
"""

from __future__ import annotations

import logging
import socket
import threading
from dataclasses import dataclass, replace
from typing import Any, Literal

import httpx
from sqlalchemy.orm import Session

from app.domain import deployment
from app.domain.community import accounts, transport
from app.domain.community.errors import CommunityError, NotConfigured, Unreachable

logger = logging.getLogger(__name__)

#: 服务端没给 `interval` 时按 RFC 8628 的缺省 5 秒。
DEFAULT_INTERVAL_SECONDS = 5.0
#: `slow_down` 一次加多少(RFC 8628 §3.5)。
SLOW_DOWN_STEP_SECONDS = 5.0

PollState = Literal["idle", "pending", "connected", "expired", "denied"]


@dataclass(frozen=True)
class DeviceFlow:
    origin: str
    device_code: str
    user_code: str
    verification_uri: str
    expires_at: float
    interval: float
    next_poll_at: float


#: user_id → 这个人正在等的那一次设备授权。见 docs/PROCESS_STATE.md。
_flows: dict[str, DeviceFlow] = {}
_flows_lock = threading.Lock()


def _client_name() -> str:
    """在网页「设备」页里认出这台机器的那个名字。"""
    try:
        host = socket.gethostname().strip()
    except OSError:
        host = ""
    return f"Mosael · {host}" if host else "Mosael"


def start(db: Session, user_id: str) -> DeviceFlow:
    """要一个设备码。已经有一个在等的,作废它、重新要 —— 用户再点一次「连接」就是要一个新的。"""
    origin = deployment.community_url(db)
    if not origin:
        raise NotConfigured()
    try:
        with transport.make_client() as http:
            response = http.post(
                transport.api_url(origin, "/auth/device/code"),
                json={"client_name": _client_name()},
                headers={"Accept-Language": accounts.accept_language()},
            )
    except httpx.HTTPError as exc:
        raise Unreachable(str(exc)) from exc
    body = accounts.read_json(response)
    device_code = str(body.get("device_code") or "")
    user_code = str(body.get("user_code") or "")
    uri = str(body.get("verification_uri_complete") or body.get("verification_uri") or "")
    if not device_code or not user_code or not uri:
        raise CommunityError("communityErr_badResponse")
    now = accounts.clock()
    interval = _seconds(body.get("interval"), DEFAULT_INTERVAL_SECONDS)
    flow = DeviceFlow(
        origin=origin,
        device_code=device_code,
        user_code=user_code,
        verification_uri=transport.absolute(origin, uri),
        expires_at=now + _seconds(body.get("expires_in"), 600.0),
        interval=interval,
        next_poll_at=now + interval,
    )
    with _flows_lock:
        _flows[user_id] = flow
    return flow


def _seconds(value: Any, fallback: float) -> float:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return fallback
    return seconds if seconds > 0 else fallback


def pending(user_id: str) -> DeviceFlow | None:
    with _flows_lock:
        flow = _flows.get(user_id)
    if flow is not None and accounts.clock() >= flow.expires_at:
        cancel(user_id)
        return None
    return flow


def cancel(user_id: str) -> None:
    with _flows_lock:
        _flows.pop(user_id, None)


def poll(user_id: str) -> PollState:
    """问一次「用户在网页上点了允许没有」。按 `interval` 节流:还没到时间就不发请求。"""
    now = accounts.clock()
    with _flows_lock:
        flow = _flows.get(user_id)
        if flow is None:
            return "idle"
        if now >= flow.expires_at:
            _flows.pop(user_id, None)
            return "expired"
        if now < flow.next_poll_at:
            return "pending"
        # 先占住下一格再出门:同一时刻来的第二次轮询看到的是「还没到时间」,不会两个一起去问。
        _flows[user_id] = replace(flow, next_poll_at=now + flow.interval)
    try:
        with transport.make_client() as http:
            response = http.post(
                transport.api_url(flow.origin, "/auth/device/token"),
                json={"device_code": flow.device_code},
            )
    except httpx.HTTPError as exc:
        # 连不上:这一轮当作还在等,下一格再问。设备码还有效,不该因为一次断网就让人重来。
        logger.info("设备授权轮询连不上社区:%s", exc)
        return "pending"
    code, _message = transport.error_of(response)
    if response.status_code == 200:
        with _flows_lock:
            if _flows.get(user_id) is None or _flows[user_id].device_code != flow.device_code:
                # 等回包的时候被取消了(或者又开了一个新的):这一对令牌不要。
                return "idle"
            _flows.pop(user_id, None)
        accounts.adopt_login(user_id, flow.origin, accounts.read_json(response))
        return "connected"
    if code == "slow_down":
        with _flows_lock:
            current = _flows.get(user_id)
            if current is not None and current.device_code == flow.device_code:
                interval = current.interval + SLOW_DOWN_STEP_SECONDS
                _flows[user_id] = replace(current, interval=interval, next_poll_at=accounts.clock() + interval)
        return "pending"
    if response.status_code == 428 or code == "authorization_pending":
        return "pending"
    if response.status_code == 410 or code in ("expired_token", "expired"):
        cancel(user_id)
        return "expired"
    if code == "access_denied" or response.status_code == 403:
        cancel(user_id)
        return "denied"
    if response.status_code >= 500:
        return "pending"
    # 认不出的拒绝(设备码不认识了之类):这一次作废,让人重来,而不是一直转圈。
    logger.info("设备授权轮询被拒:HTTP %s %s", response.status_code, code)
    cancel(user_id)
    return "expired"


def reset_for_tests() -> None:
    with _flows_lock:
        _flows.clear()
