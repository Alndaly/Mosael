from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import timedelta

from app.core.config import LOGIN_SESSION_TTL, SERVICE_SESSION_TTL
# 哈希是纯函数,单独一个模块 —— 迁移那边也要用它,而 core/db 不能认识 core/security(会成环)。
from app.core.token_digest import token_digest

"""Password hashing (stdlib PBKDF2) and opaque session tokens."""

__all__ = [
    "find_session",
    "hash_password",
    "mint_login_session",
    "mint_service_session",
    "new_session_token",
    "SERVICE_PATH_PREFIXES",
    "service_request_allowed",
    "prune_expired_sessions",
    "revoke_other_logins",
    "revoke_session",
    "renew_if_stale",
    "verify_password",
]

_ITERATIONS = 240_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), _ITERATIONS)
    return f"pbkdf2${_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, expected = stored.split("$", 3)
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def new_session_token() -> str:
    return secrets.token_hex(32)


def find_session(db, raw: str | None):
    """按来客手上那串取凭据行。**取凭据只此一处** —— 五个调用点各自 `db.get(AuthSession, token)`
    的写法漏掉任何一处都不会报错,只会让那条路径静默地认不出人来。"""
    from app.db.models import AuthSession

    if not raw:
        return None
    return db.get(AuthSession, token_digest(raw))


def revoke_session(db, raw: str | None) -> bool:
    """用完就撤(turn 令牌、登出)。回 True 表示确实删掉了一行。"""
    session = find_session(db, raw)
    if session is None:
        return False
    db.delete(session)
    return True


def revoke_other_logins(db, user_id: str, keep_raw: str | None) -> int:
    """撤掉这个人除 `keep_raw` 之外的全部**登录**凭据,返回撤了几份。不提交。

    改密码时用:察觉异常登录的人改密码,预期的是「别处都被踢下线」—— 此前只挡住了「再用旧密码登录」,已经攥着一份
    登录令牌(30 天、活跃续期)的人照样进得来(SEC-6)。服务令牌(智能体回合、工具通道)不动:它们本来就短、跟着一次
    操作走,撤了只会把正在跑的那一轮打断。
    """
    from sqlalchemy import delete

    from app.db.models import AuthSession

    keep = token_digest(keep_raw) if keep_raw else ""
    return db.execute(delete(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.kind == "login", AuthSession.token != keep,
    )).rowcount


#: 剩余不足这么多就续期。不是每次请求都写库 —— 那是一次登录换来每个请求一次 UPDATE。
LOGIN_RENEW_THRESHOLD = LOGIN_SESSION_TTL / 2
#: 回合令牌同理:剩余不足半个周期、又正被用着,就往后推一个周期。
TURN_RENEW_THRESHOLD = SERVICE_SESSION_TTL / 2


def prune_expired_sessions(db) -> int:
    """删掉所有已过期的凭据,返回删了几行。**不提交** —— 由调用方决定事务边界。

    在铸造时调用:表变大的那一刻恰好就是该清理的那一刻,增长因此自限,不需要再养一个定时任务
    (而定时任务在桌面应用里本来就不可靠 —— 进程可能几周不重启,也可能一天重启十次)。
    """
    from sqlalchemy import delete

    from app.db.models import AuthSession, now

    return db.execute(delete(AuthSession).where(AuthSession.expires_at <= now())).rowcount


def mint_login_session(db, user_id: str, *, commit: bool = True) -> str:
    """为**人**铸造一份登录凭据。

    `commit=False` 给注册流程用:用户行和会话行要么一起进库,要么都不进。
    """
    return _mint(db, user_id, kind="login", ttl=LOGIN_SESSION_TTL, commit=commit)


def mint_service_session(db, user_id: str, *, agent_session_id: str | None = None) -> str:
    """为服务侧调用(智能体回合 / 工具通道 / 飞书 bot)铸造一份短期凭据并立即提交。

    `agent_session_id` 是这次 turn 属于哪次对话。**确认卡的归属从这里来** —— 铸令牌的地方正好
    知道答案,而下游的每一跳都只是转述,转述就可以被伪造。

    AuthSession 行只在 auth 归属方创建(见 app/domain/ownership.py)——此前 agent host
    与飞书各自 `db.add(AuthSession(...))`,是归属棘轮里的存量债务;现在收敛到这里。
    立即 commit:token 马上要被带出去做回连请求,不能停留在未提交事务里。
    """
    return _mint(
        db, user_id, kind="service", ttl=SERVICE_SESSION_TTL, commit=True, agent_session_id=agent_session_id
    )


#: 服务令牌(交给 sidecar、飞书连接这类进程外的调用方)**只能**用在这几组路由上:取工具清单、调工具、
#: 等确认卡 / 选择卡的结果、回写供应商凭据 —— sidecar 用到的正好是这些(agent-sidecar/src)。此前它和登录态
#: 一样通行全部接口,半小时内谁拿到它(sidecar 进程、它起的子进程)就能以这个人的身份调任何 REST。
#: 工具体在后端进程里直接调领域用例,不再回连本 API,所以没有第二种令牌。
SERVICE_PATH_PREFIXES = (
    "/api/agent/tools",
    "/api/confirmations",
    "/api/agent/questions/",
    "/api/agent/provider-credentials",
)

#: 上面那几组里,**写**只放这几条(其余只许读)。确认卡和选择卡上它只开卡、轮询结果、「卡等到点、作废它」,不拍板。
#: 此前只按路径前缀放行,同一份令牌 POST `/api/confirmations/{id}/approve` 也过 —— 拿到这份令牌的进程就能替用户批它自己开的卡,
#: 而那正是确认卡整套机制里最不该给出去的一项(智能体那一路 AGENT-14)。答选择卡同理。
_SERVICE_WRITES = (
    re.compile(r"^/api/agent/tools(/[^/]+)?$"),
    #: 开卡是**提议**,不是拍板:卡挂在哪段对话由这份令牌决定(它铸的时候记着是哪一轮),批不批照样是人。
    re.compile(r"^/api/confirmations$"),
    re.compile(r"^/api/confirmations/[^/]+/expire$"),
    re.compile(r"^/api/agent/provider-credentials/[^/]+/(acquire|commit|renew|release)$"),
)


def service_request_allowed(method: str, path: str) -> bool:
    """服务令牌能不能走这一条:路径在那几组里,而且是读、或者是那几条写之一。"""
    if not path.startswith(SERVICE_PATH_PREFIXES):
        return False
    if method.upper() in ("GET", "HEAD", "OPTIONS"):
        return True
    return any(rule.match(path) for rule in _SERVICE_WRITES)


def _mint(
    db,
    user_id: str,
    *,
    kind: str,
    ttl: timedelta,
    commit: bool,
    agent_session_id: str | None = None,
) -> str:
    from app.db.models import AuthSession, now

    prune_expired_sessions(db)
    token = new_session_token()
    db.add(
        AuthSession(
            token=token_digest(token),
            user_id=user_id,
            kind=kind,
            expires_at=now() + ttl,
            agent_session_id=agent_session_id,
        )
    )
    if commit:
        db.commit()
    return token


def renew_if_stale(db, session) -> None:
    """被用到的凭据往后续 —— 用着用着被踢出去是回归,不是安全。

    服务令牌的周期由**那次操作**决定,不由它被用了多少次决定,所以续不续看它属于哪种操作:

    - `login`:「这个人还在用这台机器」,活跃就续一个登录周期;
    - **回合令牌**(带 `agent_session_id` 的服务令牌):那次操作就是这一轮对话。一轮要等出图、出视频,
      跑上一个小时是常态 —— 此前它和设备码登录一样定死半小时,长回合跑到一半所有工具一齐 401
      (「Invalid or expired session」),导出那一步永远到不了。现在它跟着回合活:被用着就再续半小时,
      回合结束由 host 撤销;没人再用,半小时后自己过期 —— 泄漏的代价仍然被这一轮的长度封住;
    - 其余服务令牌(设备码登录、OAuth 刷新、上下文压缩):一次性的短操作,不续。
    """
    from app.db.models import now

    if session.kind == "login":
        threshold, ttl = LOGIN_RENEW_THRESHOLD, LOGIN_SESSION_TTL
    elif session.kind == "service" and session.agent_session_id:
        threshold, ttl = TURN_RENEW_THRESHOLD, SERVICE_SESSION_TTL
    else:
        return
    moment = now()
    if session.expires_at - moment > threshold:
        return
    session.expires_at = moment + ttl
    db.commit()
