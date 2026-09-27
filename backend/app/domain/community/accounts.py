"""社区账号:刷新令牌落盘(加密),访问令牌在内存,以及一个会自己续期的客户端。

## 两种令牌住在两个地方(ADR 0026 §3)

- **刷新令牌**:`community_accounts.refresh_token`,和服务商密钥同一种加密列(core/secrets_at_rest)。
  它只在这个模块里被读出来,只发给社区的 `/auth/refresh`;不写日志、不进任何接口的回包。
- **访问令牌**:15 分钟,只在进程内存里(`_access`)。进程重启丢了就用刷新令牌再换一个。

## 续期的规矩

- **提前续**:离过期不到 60 秒就先换一对再发请求。
- **收到 401 只续一次**,续完**重放一次**;重放还是 401 → 本机存的令牌删掉,报「社区账号已退出」。
- **同一个人同一时刻只有一个续期在飞**(`_refresh_locks`)。几个请求同时撞上 401 时,第一个去换,
  其余的等它、然后直接用它换来的那一枚 —— 刷新令牌是轮换的,两个人各拿旧的去换,第二个就是在「重用
  已经换掉的令牌」,服务端会把整个会话判成被盗、全部吊销(ADR 0026 的 20 秒宽限期只是兜底)。
- **轮换先落盘再用**:换来的新刷新令牌先写进库、提交成功,然后才把新的访问令牌交给调用方。反过来的话,
  进程在两步之间没了,库里留着的是一枚已经被换掉的旧令牌 —— 下次启动一用就触发盗用判定。
- 刷新接口说这枚刷新令牌不算数了(吊销、被判重用、过期)→ 删掉本机存的,报「社区账号已退出」。
  **连不上**不删:断网不等于被退出。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.http_retry import auth_headers
from app.core.i18n import get_current_locale
from app.db.models import CommunityAccount, now
from app.domain import deployment
from app.domain.community import transport
from app.domain.community.errors import (
    CommunityError,
    NoCommunityHere,
    NotConfigured,
    NotConnected,
    Rejected,
    SignedOut,
    Unreachable,
)

logger = logging.getLogger(__name__)

#: 离过期还剩多少秒就提前续。和网页那一侧同一个数(ADR 0026 §3「到期前 60 秒主动刷新」)。
PROACTIVE_REFRESH_SECONDS = 60
#: 刷新接口在这些状态码上说的是「这枚刷新令牌不再有效」—— 吊销、被判重用、过期、不认识。
REVOKED_STATUSES = frozenset({400, 401, 403, 410})


@dataclass(frozen=True)
class AccessToken:
    token: str
    #: 墙钟秒(`clock()`),不是 monotonic —— 它来自服务端给的 `expires_in`,只用来决定「该不该提前续」。
    expires_at: float
    origin: str


#: user_id → 当前的访问令牌。见 docs/PROCESS_STATE.md。
_access: dict[str, AccessToken] = {}
#: user_id → 这个人的续期锁(single-flight)。见 docs/PROCESS_STATE.md。
_refresh_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def clock() -> float:
    """现在(墙钟秒)。测试换成一个可以拨的钟。"""
    return time.time()


def _lock_for(user_id: str) -> threading.Lock:
    with _locks_guard:
        lock = _refresh_locks.get(user_id)
        if lock is None:
            lock = threading.Lock()
            _refresh_locks[user_id] = lock
        return lock


def accept_language() -> str:
    """社区服务按 Accept-Language 给中文或英文的 message;跟着这次请求的语言走。"""
    return "zh-CN" if get_current_locale() == "zh" else "en"


def _remember(user_id: str, origin: str, token: str, expires_in: Any) -> str:
    try:
        seconds = max(0.0, float(expires_in))
    except (TypeError, ValueError):
        seconds = 0.0
    _access[user_id] = AccessToken(token=token, expires_at=clock() + seconds, origin=origin)
    return token


def forget(user_id: str) -> None:
    """删掉这个人在本机存的社区令牌(库里的刷新令牌 + 内存里的访问令牌)。"""
    _access.pop(user_id, None)
    with SessionLocal() as db:
        row = db.get(CommunityAccount, user_id)
        if row is not None:
            db.delete(row)
            db.commit()


def _tokens_of(payload: Any) -> tuple[str, str, Any, dict[str, Any]]:
    """登录 / 刷新的回包 → (访问令牌, 刷新令牌, expires_in, user)。缺了哪一样都不认。"""
    if not isinstance(payload, dict):
        raise CommunityError("communityErr_badResponse")
    access = str(payload.get("access_token") or "")
    refresh = str(payload.get("refresh_token") or "")
    if not access or not refresh:
        raise CommunityError("communityErr_badResponse")
    user = payload.get("user") if isinstance(payload.get("user"), dict) else {}
    return access, refresh, payload.get("expires_in"), user


def _fill_identity(row: CommunityAccount, user: dict[str, Any]) -> None:
    if not user:
        return
    row.community_user_id = str(user.get("id") or row.community_user_id or "")[:64]
    row.handle = str(user.get("handle") or row.handle or "")[:64]
    row.display_name = str(user.get("display_name") or row.display_name or "")[:120]


def adopt_login(user_id: str, origin: str, payload: Any) -> CommunityAccount:
    """设备授权拿到的第一对令牌:落盘(刷新令牌)+ 记进内存(访问令牌)。换号时覆盖旧的那一行。"""
    access, refresh, expires_in, user = _tokens_of(payload)
    with SessionLocal() as db:
        row = db.get(CommunityAccount, user_id)
        if row is None:
            row = CommunityAccount(user_id=user_id)
            db.add(row)
        row.origin = origin
        row.refresh_token = refresh
        row.connected_at = now()
        row.handle = row.community_user_id = row.display_name = ""
        _fill_identity(row, user)
        db.commit()
        db.refresh(row)
        db.expunge(row)
    _remember(user_id, origin, access, expires_in)
    return row


def _store_rotated(user_id: str, origin: str, payload: Any) -> str:
    """刷新换来的一对:**先把新刷新令牌提交进库**,再让新的访问令牌生效(见模块说明)。"""
    access, refresh, expires_in, user = _tokens_of(payload)
    with SessionLocal() as db:
        row = db.get(CommunityAccount, user_id)
        if row is None or row.origin != origin:
            # 换的这一会儿里人已经断开了(或者管理员换了社区):换来的这一对没有地方放,也不该用。
            _access.pop(user_id, None)
            raise SignedOut()
        row.refresh_token = refresh
        _fill_identity(row, user)
        db.commit()
    return _remember(user_id, origin, access, expires_in)


def _stored_refresh_token(user_id: str, origin: str) -> str:
    with SessionLocal() as db:
        row = db.get(CommunityAccount, user_id)
        if row is None or not row.refresh_token:
            raise NotConnected()
        if row.origin != origin:
            raise NotConnected()
        return row.refresh_token


def account_of(db: Session, user_id: str) -> CommunityAccount | None:
    """这个人连着的社区账号 —— **连的是当前配置的那个社区**才算。管理员换了地址,旧账号按没连处理。"""
    row = db.get(CommunityAccount, user_id)
    origin = deployment.community_url(db)
    if row is None or not origin or row.origin != origin or not row.refresh_token:
        return None
    return row


class CommunityClient:
    """替**一个人**向社区服务发请求。续期、重放、single-flight 都在这里,调用方只管发。"""

    def __init__(self, user_id: str, origin: str) -> None:
        self.user_id = user_id
        self.origin = origin

    @classmethod
    def for_user(cls, db: Session, user_id: str) -> CommunityClient:
        """没配社区 → NotConfigured;没连账号 → NotConnected。"""
        origin = deployment.community_url(db)
        if not origin:
            raise NotConfigured()
        if account_of(db, user_id) is None:
            raise NotConnected()
        return cls(user_id, origin)

    def url(self, path: str) -> str:
        return transport.api_url(self.origin, path)

    def owns(self, url: str) -> bool:
        """这个地址是不是社区服务自己的(本地存储的上传地址)—— 是才带访问令牌;预签名的对象存储地址不带。"""
        return url.startswith(self.origin.rstrip("/") + "/")

    # --- 令牌 ---------------------------------------------------------------

    def _current_token(self) -> str:
        current = _access.get(self.user_id)
        if current is not None and current.origin == self.origin and current.expires_at - clock() > PROACTIVE_REFRESH_SECONDS:
            return current.token
        return self._refresh(stale=current.token if current is not None else None)

    def _refresh(self, *, stale: str | None) -> str:
        """换一对新令牌。`stale` 是调用方手里那枚(被拒了、或快过期了)——等锁期间别人已经换过的话,直接用别人换来的。"""
        with _lock_for(self.user_id):
            current = _access.get(self.user_id)
            if (
                current is not None
                and current.origin == self.origin
                and current.token != stale
                and current.expires_at - clock() > PROACTIVE_REFRESH_SECONDS
            ):
                return current.token
            refresh_token = _stored_refresh_token(self.user_id, self.origin)
            try:
                with transport.make_client() as http:
                    response = http.post(
                        self.url("/auth/refresh"),
                        json={"refresh_token": refresh_token},
                        # 网页那一侧靠这个头配合 SameSite 防 CSRF(ADR 0026 §3);带 body 的应用请求照样带上,不让服务端分两种。
                        headers={"X-Requested-With": "Mosael", "Accept-Language": accept_language()},
                    )
            except httpx.HTTPError as exc:
                raise Unreachable(str(exc)) from exc
            if response.status_code in REVOKED_STATUSES:
                logger.info("社区刷新令牌已失效(HTTP %s),删掉本机存的那一份(user=%s)", response.status_code, self.user_id)
                forget(self.user_id)
                raise SignedOut()
            if response.status_code >= 400:
                raise Unreachable(f"HTTP {response.status_code}")
            try:
                payload = response.json()
            except ValueError as exc:
                raise CommunityError("communityErr_badResponse") from exc
            return _store_rotated(self.user_id, self.origin, payload)

    # --- 请求 ---------------------------------------------------------------

    def _send(self, method: str, url: str, token: str | None, options: dict[str, Any]) -> httpx.Response:
        options = dict(options)
        headers = {"Accept-Language": accept_language(), **(options.pop("headers", None) or {}), **auth_headers(token)}
        content = options.pop("content", None)
        if callable(content):
            # 能重放的正文:每发一次现取一份(文件流读完就空了,重放时要从头再来)。
            content = content()
        timeout = options.pop("timeout", transport.TIMEOUT_SECONDS)
        try:
            with transport.make_client(timeout=timeout) as http:
                return http.request(method, url, headers=headers, content=content, **options)
        except httpx.HTTPError as exc:
            raise Unreachable(str(exc)) from exc

    def request(self, method: str, path_or_url: str, *, authed: bool = True, **options: Any) -> httpx.Response:
        """发一个请求,拿回最终的响应(状态码由调用方看)。

        `authed=False`:不带令牌(预签名的上传地址)。带令牌时:提前续、401 续一次再重放一次,
        重放仍是 401 → 删令牌、抛 SignedOut。连不上抛 Unreachable。
        """
        url = path_or_url if path_or_url.startswith(("http://", "https://")) else self.url(path_or_url)
        if not authed:
            return self._send(method, url, None, options)
        token = self._current_token()
        response = self._send(method, url, token, options)
        if response.status_code != 401:
            return response
        token = self._refresh(stale=token)
        response = self._send(method, url, token, options)
        if response.status_code == 401:
            logger.info("社区接口续期之后仍然 401,删掉本机存的令牌(user=%s)", self.user_id)
            forget(self.user_id)
            raise SignedOut()
        return response

    def call(self, method: str, path: str, **options: Any) -> dict[str, Any]:
        """发一个请求并读回 JSON。对方拒绝 → Rejected(带对方的原话);对方 5xx → Unreachable。"""
        response = self.request(method, path, **options)
        return read_json(response)


def read_json(response: httpx.Response) -> dict[str, Any]:
    if response.status_code >= 500:
        raise Unreachable(f"HTTP {response.status_code}")
    if response.status_code >= 400:
        code, message = transport.error_of(response)
        if not code:
            # 社区服务的每一种出错都带错误信封(包括不存在的路由、请求体校验失败);没有,说明那里不是社区。
            url = response.request.url
            raise NoCommunityHere(f"{url.scheme}://{url.netloc.decode()}", response.status_code)
        raise Rejected(response.status_code, code, message)
    if response.status_code == 204 or not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError as exc:
        raise CommunityError("communityErr_badResponse") from exc
    if not isinstance(payload, dict):
        raise CommunityError("communityErr_badResponse")
    return payload


def disconnect(db: Session, user_id: str) -> None:
    """断开:先请社区吊销这台设备的会话(`/auth/logout`),再删本机存的令牌。

    吊销是**尽力而为**:连不上、令牌早已失效,本机照样删 —— 用户要的是「这台机器不再连着我的账号」,
    那件事只取决于本机;服务端那个会话在网页「设备」页里也看得到、撤得掉。
    """
    origin = deployment.community_url(db)
    if origin and account_of(db, user_id) is not None:
        try:
            CommunityClient(user_id, origin).request("POST", "/auth/logout")
        except CommunityError as exc:
            logger.info("断开社区账号时吊销会话没成(本机照样删):%s", exc.key)
    forget(user_id)


def status(db: Session, user_id: str) -> dict[str, Any]:
    """设置页那一节要的:配没配社区、连没连、连的是谁。"""
    origin = deployment.community_url(db)
    row = account_of(db, user_id)
    return {
        "configured": bool(origin),
        "origin": origin,
        "connected": row is not None,
        "handle": row.handle if row else "",
        "display_name": row.display_name if row else "",
    }


def reset_for_tests() -> None:
    """测试之间清掉内存里的令牌和锁(库每条测试都重建,内存不会)。"""
    _access.clear()
    with _locks_guard:
        _refresh_locks.clear()
