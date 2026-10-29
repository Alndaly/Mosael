"""密码、令牌、设备码 —— 都用成熟实现,不自制。

- 密码:argon2-cffi 的 `PasswordHasher`,缺省就是 argon2id。参数用库的缺省(它跟着 OWASP 的
  推荐走),不自己调成"看起来更安全"的数字。
- 会话令牌:256 位随机(`secrets.token_urlsafe(32)`),库里只存 sha256。
  这不是加密 —— 令牌本身是随机数,哈希只是让库文件泄露时别人拿不到可用的令牌。
"""

from __future__ import annotations

import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored: str) -> bool:
    try:
        return _hasher.verify(stored, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError, TypeError, ValueError):
        return False


def new_token(nbytes: int = 32) -> str:
    """256 位随机串。`token_urlsafe(32)` 的长度是 43,测试按"至少 43"钉住。"""
    return secrets.token_urlsafe(nbytes)


def token_digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def new_email_code() -> str:
    """6 位数字验证码,允许前导 0。逐位 `secrets.choice`,不用取模(避免偏置)。"""
    return "".join(secrets.choice("0123456789") for _ in range(6))


def phone_code_digest(phone: str, purpose: str, code: str) -> str:
    payload = f"{purpose}:{phone}:{code}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def email_code_digest(email: str, purpose: str, code: str) -> str:
    """验证码的 sha256。

    把 email 和 purpose 一起拌进去:库泄露时,同一串数字在不同邮箱 / 用途下不是同一个哈希,
    不能拿一张彩虹表横着比对。**6 位数字只有 100 万种,hash 本身挡不住离线穷举** ——
    真正的防线是 10 分钟 TTL、一次性、5 次尝试作废和重发限流(见 `email_codes.py`)。
    """
    payload = f"{purpose}:{email}:{code}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
