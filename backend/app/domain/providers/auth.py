"""OAuth 凭据的存放与互斥刷新。

**为什么需要互斥而不是「谁写谁算」**:订阅制凭据(Claude Pro/Max、Kimi Code 等)的 refresh
token 通常是**一次性**的 —— 换出新 access token 的同时旧 refresh 作废。而 Mosael 每一轮
对话都会新起一个 sidecar 进程,多个会话(对话页 / 工作流 / 飞书)可以同时开工。两个 sidecar
若同时拿同一份凭据去刷新,后手那次会让先手刚存进来的凭据当场失效,用户看到的是「刚登录就被
登出」,而且是偶发、不可复现的那种。

版本号式的乐观并发在这里**不够**:冲突检测发生在写入时,可那时两次刷新都已经打过网络了,
损害已经造成。所以这里给的是租约(lease):sidecar 先取得该档案的独占权和当前凭据,刷新完再
带着租约写回。这正是 pi 的 CredentialStore.modify 契约要的语义(「跨进程互斥」)。

租约放在进程内存里:后端是单进程 uvicorn(见 run_backend.py),sidecar 才是多进程,而它们
都经由后端 —— 内存锁就是**这套进程拓扑下**真正的临界区。带 TTL 是因为持有者会崩(sidecar
被杀、超时),不能让一次崩溃把某个供应商永久锁死。

后半截是**设置页上的自动续期**(`refresh_expired_in_background`):列连接时顺手把过期的订阅令牌
在后台刷一遍,刷不动的记进一张冷却表(`refresh_recently_failed`),界面据此才说「需重新授权」。
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.sidecar.adapters import AdapterError, refresh_oauth_credential
from app.core.config import settings
from app.core.i18n import LocalizedError
from app.db.models import ProviderCredential, ProviderProfile
from app.domain import provider_credentials
from app.domain.provider_quota import is_expired
from app.domain.providers import pi_provider_id

#: 持有租约期间只做一次刷新 HTTP 调用,给足余量。超过即视为持有者已死。
LEASE_TTL_SECONDS = 30.0
#: 等待他人释放的上限。刷新本身通常一秒内完成;等不到就让调用方重试而不是无限期挂住一轮对话。
ACQUIRE_TIMEOUT_SECONDS = 20.0
_POLL_SECONDS = 0.05

AUTH_TYPES = ("api_key", "oauth")

logger = logging.getLogger(__name__)


class CredentialLeaseError(LocalizedError, RuntimeError):
    """租约不可用。

    `code` 是给**另一个运行时**看的:sidecar 收到 409 时必须分得清这两件事,
    因为它们要的处置**正好相反**(见 `commit_credential` 的说明)。
    消息文本给人看,`code` 给机器看 —— 和 `error` 事件上已有的 `code: "output_limit"` 同一个做法。
    """

    def __init__(self, key: str, code: str = "lease_unavailable", **params: object) -> None:
        super().__init__(key, **params)
        self.code = code


@dataclass
class _Lease:
    token: str
    expires_at: float


_leases: dict[str, _Lease] = {}
_lock = threading.Lock()


def _now() -> float:
    return time.monotonic()


def _lease_key(profile_id: str, user_id: str) -> str:
    """租约按 (连接, 人) 键。

    凭据归人之后,两个人在同一条连接上各刷各的钥匙是完全独立的两件事 —— 按档案键会让他们
    互相阻塞,而互斥本来要防的是「同一把钥匙被刷两次」。
    """
    return f"{profile_id}:{user_id}"


def acquire_lease(profile_id: str, user_id: str, *, timeout: float = ACQUIRE_TIMEOUT_SECONDS) -> str:
    """取得**我自己**那把钥匙的独占写入权,返回租约 token。"""
    key = _lease_key(profile_id, user_id)
    deadline = _now() + timeout
    while True:
        with _lock:
            held = _leases.get(key)
            if held is None or held.expires_at <= _now():
                token = secrets.token_urlsafe(16)
                _leases[key] = _Lease(token=token, expires_at=_now() + LEASE_TTL_SECONDS)
                return token
        if _now() >= deadline:
            raise CredentialLeaseError("credLeaseErr_busy", code="busy")
        time.sleep(_POLL_SECONDS)


def renew_lease(profile_id: str, user_id: str, token: str) -> bool:
    """续租。持有者在刷新期间定期调它,让 TTL 只用来发现**死掉的**持有者,而不是罚慢的那个。

    TTL 短是对的(持有者崩了不能把某个供应商永久锁死),但一次跨境 OAuth 刷新还要走用户配的
    出网代理,30 秒并不宽裕。不续租的话,慢一点就会被别人顶替 —— 于是**两个 sidecar 同时拿
    同一份凭据去刷新**,正是模块开头说的那个灾难。
    """
    key = _lease_key(profile_id, user_id)
    with _lock:
        held = _leases.get(key)
        if held is None or held.token != token:
            return False
        _leases[key] = _Lease(token=token, expires_at=_now() + LEASE_TTL_SECONDS)
        return True


def release_lease(profile_id: str, user_id: str, token: str) -> None:
    """释放租约。token 不匹配(自己的租约已超时被顶替)时静默返回 —— 顶替者的租约不该被误伤。"""
    key = _lease_key(profile_id, user_id)
    with _lock:
        held = _leases.get(key)
        if held is not None and held.token == token:
            _leases.pop(key, None)


def _check_lease(key: str, token: str) -> None:
    with _lock:
        held = _leases.get(key)
    if held is not None and held.token != token:
        # 有**别人**正拿着它 —— 他刷出来的才是新的,我这份该丢。
        raise CredentialLeaseError("credLeaseErr_superseded", code="superseded")
    if held is None or held.expires_at <= _now():
        # 没有别人,只是我自己慢了。这两件事长得像,处置正好相反。
        raise CredentialLeaseError("credLeaseErr_expired", code="expired")


def read_credential(credential: ProviderCredential | None) -> dict | None:
    """这把钥匙上存着的 OAuth 凭据(pi 的 Credential 原样),没有则 None。

    参数是**一把具体的钥匙**而不是档案:凭据归人之后,「这个档案的凭据」不再是一个有答案的
    问题 —— 得先说清是谁的(见 domain/provider_credentials)。
    """
    stored = credential.oauth_credential if credential is not None else None
    return dict(stored) if isinstance(stored, dict) else None


def commit_credential(
    db: Session, profile_id: str, user_id: str, lease_token: str, credential: dict | None,
    *, base_version: int | None = None,
) -> ProviderCredential:
    """持租约写回凭据(credential=None 即登出)。写完即释放。

    凭据**原样**存:各家 OAuth 的附加字段由 pi 解释,这里拆一次就等于把协议复制进 Python。
    只校验最低限度的形状,把明显不是凭据的东西挡在库外。

    ## 租约过期时为什么**照写不误**

    订阅制的 refresh token 是一次性的:换出新 access token 的同时旧的作废(见模块开头)。
    所以调用方手上这份 `credential` 是**刚换出来的、唯一有效的**那一份 —— 拒绝写入不是"保守",
    而是把它丢掉,库里留着一个已经被供应商作废的 refresh token。下一轮 `invalid_grant`,
    用户被登出。**而这正是整套租约机制存在的全部理由**,它原先在自己的收尾分支上被重新引入了。

    互斥要防的是「两次刷新互相覆盖」。判据因此不是「我的租约还在不在」,而是
    **「我拿到租约之后,有没有别人写过」** —— 那是 `credential_version` 精确回答得了的问题。
    没人写过就没有什么需要保护,照写;写过了才该丢掉我这份(`superseded`)。

    `base_version` 由调用方在 acquire 时拿到并带回来。不传时退回旧行为(严格拒绝),
    这样没升级的调用方不会突然变得更宽松。
    """
    key = _lease_key(profile_id, user_id)
    try:
        _check_lease(key, lease_token)
    except CredentialLeaseError as exc:
        stored = provider_credentials.get(db, profile_id, user_id)
        current_version = (stored.credential_version if stored else 0) or 0
        if base_version is None or current_version != base_version:
            raise
        logger.warning(
            "provider %s 的租约已过期(%s),但这期间没有别人写过(v%s)—— 照写:"
            "这份凭据是刚换出来的唯一有效的那一份,丢掉它下一轮就会 invalid_grant",
            profile_id, exc.code, current_version,
        )
    profile = db.get(ProviderProfile, profile_id)
    if profile is None or profile.owner_user_id != user_id:
        release_lease(profile_id, user_id, lease_token)
        raise CredentialLeaseError("credLeaseErr_providerNotFound")
    if credential is not None:
        if not isinstance(credential, dict) or credential.get("type") not in AUTH_TYPES:
            release_lease(profile_id, user_id, lease_token)
            raise CredentialLeaseError("credLeaseErr_badCredential")
    row = provider_credentials.upsert(db, profile_id, user_id)
    row.oauth_credential = credential
    row.credential_version = (row.credential_version or 0) + 1
    db.commit()
    db.refresh(row)
    release_lease(profile_id, user_id, lease_token)
    return row


# ---------------- 设置页上的自动续期 ----------------

#: 刷新失败后多久才再试一次。失败通常不会因为再试而变好(refresh token 被吊销、账号在别处
#: 登出),而档案列表是设置页最常被拉的那个接口 —— 没有冷却就会变成每次进页面都起一次
#: node 去撞同一堵墙,页面还跟着卡。
_REFRESH_COOLDOWN_SECONDS = 300.0
_refresh_failed_at: dict[str, float] = {}


def refresh_recently_failed(profile_id: str) -> bool:
    """这条连接最近一次自动刷新令牌失败了没有。

    进程级内存:重启后是空的,于是重启后第一次拉列表会说「已授权」,哪怕它其实刷不动 ——
    下一次就对了。这个方向是**有意选的**:把"还不知道"说成"已授权"只会晚一次发现,
    而把它说成"需重新授权"是在没坏的时候喊坏,后者用户已经撞上了。
    """
    failed_at = _refresh_failed_at.get(profile_id)
    return failed_at is not None and time.monotonic() - failed_at < _REFRESH_COOLDOWN_SECONDS


def refresh_expired_in_background(
    connections: list[tuple[ProviderProfile, ProviderCredential | None]], *, mint_token: Callable[[], str]
) -> None:
    """过期就去刷一次 —— **在后台**,不占着这次请求。`connections` 是连接和**我自己**那把钥匙。

    **过期本身不是一个需要用户知道的状态**:订阅计划的 access token 普遍只有几小时,刷新是协议
    里就有的一步。此前只有对话路径和查额度会触发刷新,于是"隔夜再打开设置页"必然看到一行已过期
    —— 而它其实只要被用到就会自己好。

    **但它不能挡在列表前面。** 刷新是:起一个 Node 子进程(pi sidecar)→ 向那家供应商发一次
    网络请求 → 最长等 60 秒;而且每条过期连接串着来。断网或那家挂掉时,一件本地的纯读的事
    (告诉我我配了哪些连接)被一件远程的可选的事拖到几十秒 —— 用户看到的是设置页一直
    「正在连接后端…」,而日志里只有一行 fetch failed。

    判据:**列连接这个问题,不需要出网就能回答。** 所以先把列表给他,刷新在后台跑,下一次拉列表时
    状态自己就对了。刷不动才让 `refresh_recently_failed` 为真 —— 那时是真的要重新授权。

    `mint_token` 给 sidecar 回调后端用的令牌:后台线程拿不到这次请求的身份,只在真有要刷的时候
    才铸。它由调用方传进来,本模块不 import 智能体宿主 —— 那边反过来依赖连接这一族。
    """
    oauth = [
        (profile, credential)
        for profile, row in connections
        if profile.auth_type == "oauth" and (credential := read_credential(row)) is not None
    ]
    for profile, credential in oauth:
        if not is_expired(credential):
            _refresh_failed_at.pop(profile.id, None)
    pending = [
        (profile.id, profile.name, profile.vendor, credential)
        for profile, credential in oauth
        if is_expired(credential)
    ]
    if pending:
        threading.Thread(target=_refresh_in_background, args=(mint_token(), pending), daemon=True).start()


def _refresh_in_background(token: str, pending: list[tuple[str, str, str, dict]]) -> None:
    """后台把过期的订阅令牌刷一遍。失败只记日志 —— 它本来就是"顺手做的事"。"""
    now = time.monotonic()
    for profile_id, name, vendor, credential in pending:
        if refresh_recently_failed(profile_id):
            continue
        try:
            refresh_oauth_credential(
                api_base=f"http://{settings.backend_host}:{settings.backend_port}",
                token=token,
                pi_provider=pi_provider_id(vendor) or "",
                profile_id=profile_id,
                credential=credential,
            )
        except AdapterError as exc:
            logger.warning("刷新 %s 的订阅令牌失败:%s", name, exc)
            _refresh_failed_at[profile_id] = now
            continue
        _refresh_failed_at.pop(profile_id, None)
