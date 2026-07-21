from __future__ import annotations

import hashlib
import hmac
import secrets

"""Password hashing (stdlib PBKDF2) and opaque session tokens."""

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


def mint_service_session(db, user_id: str) -> str:
    """为服务侧调用(智能体回合 / 工具通道 / 飞书 bot)铸造一个会话 token 并立即提交。

    AuthSession 行只在 auth 归属方创建(见 app/domain/ownership.py)——此前 agent host
    与飞书各自 `db.add(AuthSession(...))`,是归属棘轮里的存量债务;现在收敛到这里。
    立即 commit:token 马上要被带出去做回连请求,不能停留在未提交事务里。
    """
    from app.db.models import AuthSession

    token = new_session_token()
    db.add(AuthSession(token=token, user_id=user_id))
    db.commit()
    return token
