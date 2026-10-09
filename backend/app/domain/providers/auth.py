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
在后台刷一遍;刷不动的进一张冷却表(`refresh_recently_failed`),免得每次进设置页都去撞同一堵墙。要不要重新授权
不看它,看对方有没有明确拒绝(见「刷新被对方拒绝」那一节)。
"""

from __future__ import annotations

import logging
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.ai.sidecar.pi_client import SidecarError, refresh_oauth_credential, refresh_was_rejected
from app.core.config import settings
from app.core.i18n import LocalizedError
from app.core.unit_of_work import after_commit
from app.db.models import ProviderCredential, ProviderProfile
from app.db.models import now as models_now
from app.domain.providers import credentials as provider_credentials
from app.domain.providers.quota import is_expired
from app.domain.providers.selection import pi_provider_id

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
    问题 —— 得先说清是谁的(见 domain/providers/credentials)。
    """
    stored = credential.oauth_credential if credential is not None else None
    return dict(stored) if isinstance(stored, dict) else None


def commit_credential(
    db: Session, profile_id: str, user_id: str, lease_token: str, credential: dict | None,
    *, base_version: int | None = None,
) -> ProviderCredential:
    """持租约写回凭据(credential=None 即登出)。入口提交之后释放租约。

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
    #: 写进来的是一份新凭据(刷新成功、重新授权、登出):对方拒绝的是**上一份**,那句「要重新授权」跟着它走。
    row.oauth_rejected_at = None
    row.credential_version = (row.credential_version or 0) + 1
    db.flush()
    db.refresh(row)
    # 租约**提交之后**才放:放早了,下一个持有者读到的还是旧版本,拿作废的 refresh token 去换,当场 invalid_grant。
    # 提交归入口(路由的 Tx);没提交成(回滚)就不放,等 TTL 收回 —— 和此前提交失败时一样。
    after_commit(db, lambda: release_lease(profile_id, user_id, lease_token))
    return row


# ---------------- 刷新被对方拒绝:要重新授权 ----------------
#
# 订阅凭据的刷新都由 pi 在 sidecar 里做,而且都走同一条路:CredentialStore.modify → acquire → 刷新 → commit;刷新抛错时
# sidecar 带着那句错误来 release(见 agent-sidecar/src/credentials.ts)。对话、设置页的自动续期、查额度、拉模型目录 ——
# 谁触发的刷新都从这一处过,所以「刷不动了」在这一处判、在这一处记,不按触发的入口、也不按供应商各写一遍。
#
# **只认对方明确的拒绝。** 网络不通、超时、对方 5xx 不是「授权失效」—— 下次多半就好,把它说成要重新授权是在没坏的时候
# 喊坏。判据只有一份:pi_client.refresh_was_rejected(对话那一路把同一种失败说成「去重新授权」,用的也是它)。

def note_refresh_failure(db: Session, profile_id: str, user_id: str, error: str) -> bool:
    """记下一次刷新失败。对方明确拒绝的,这份凭据记成「要重新授权」(不提交);返回记了没有。"""
    if not refresh_was_rejected(error):
        logger.warning("provider %s 的订阅凭据这次没刷成(不是对方拒绝,不改状态):%s", profile_id, error[:300])
        return False
    row = provider_credentials.get(db, profile_id, user_id)
    if row is None or row.oauth_credential is None:
        return False
    if row.oauth_rejected_at is None:
        row.oauth_rejected_at = models_now()
        logger.warning("provider %s 的订阅凭据被对方拒绝,记成要重新授权:%s", profile_id, error[:300])
    return True


def needs_reauthorization(credential: ProviderCredential | None) -> bool:
    """这把钥匙上的订阅凭据是不是被对方拒绝过、还没重新授权。"""
    return credential is not None and credential.oauth_credential is not None and credential.oauth_rejected_at is not None


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
        #: 被对方拒绝过的不再去刷:换不出来,只会再撞一次同一堵墙。重新授权会清掉那个标记。
        if profile.auth_type == "oauth" and not needs_reauthorization(row) and (credential := read_credential(row)) is not None
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
        except SidecarError as exc:
            logger.warning("刷新 %s 的订阅令牌失败:%s", name, exc)
            _refresh_failed_at[profile_id] = now
            continue
        except Exception:
            #: SidecarError 之外的(比如 spawn 子进程的 OSError):此前线程无声死掉,后面排着的
            #: 连接全部不刷、也没人知道 —— 界面上那条连接永远停在「过期」而不是「需要重新授权」。
            #: 记全堆栈、给它置上失败标记,然后接着刷后面排着的。
            logger.exception("刷新 %s 的订阅令牌时出了预想不到的错", name)
            _refresh_failed_at[profile_id] = now
            continue
        _refresh_failed_at.pop(profile_id, None)
