from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import timedelta

from app.core.config import LOGIN_SESSION_TTL, SERVICE_SESSION_TTL

"""Password hashing (stdlib PBKDF2) and opaque session tokens."""

__all__ = [
    "LOGIN_SESSION_TTL",
    "SERVICE_SESSION_TTL",
    "hash_password",
    "mint_login_session",
    "mint_service_session",
    "new_session_token",
    "prune_expired_sessions",
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


#: 剩余不足这么多就续期。不是每次请求都写库 —— 那是一次登录换来每个请求一次 UPDATE。
LOGIN_RENEW_THRESHOLD = LOGIN_SESSION_TTL / 2


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


def mint_service_session(db, user_id: str) -> str:
    """为服务侧调用(智能体回合 / 工具通道 / 飞书 bot)铸造一份短期凭据并立即提交。

    AuthSession 行只在 auth 归属方创建(见 app/domain/ownership.py)——此前 agent host
    与飞书各自 `db.add(AuthSession(...))`,是归属棘轮里的存量债务;现在收敛到这里。
    立即 commit:token 马上要被带出去做回连请求,不能停留在未提交事务里。
    """
    return _mint(db, user_id, kind="service", ttl=SERVICE_SESSION_TTL, commit=True)


def _mint(db, user_id: str, *, kind: str, ttl: timedelta, commit: bool) -> str:
    from app.db.models import AuthSession, now

    prune_expired_sessions(db)
    token = new_session_token()
    db.add(AuthSession(token=token, user_id=user_id, kind=kind, expires_at=now() + ttl))
    if commit:
        db.commit()
    return token


def renew_if_stale(db, session) -> None:
    """登录会话被用到就往后续 —— 用着用着被登出是回归,不是安全。

    只续 `login`:服务令牌的周期由那次操作决定,不由它被用了多少次决定,续期会把一份本该
    半小时后消失的凭据变成长期的。
    """
    from app.db.models import now

    if session.kind != "login":
        return
    moment = now()
    if session.expires_at - moment > LOGIN_RENEW_THRESHOLD:
        return
    session.expires_at = moment + LOGIN_SESSION_TTL
    db.commit()
