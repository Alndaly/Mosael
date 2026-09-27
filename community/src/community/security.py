"""密码(argon2id)、手机号、用户名的规则,以及密码登录按账号 / 按 IP 两个维度的失败限速。"""

from __future__ import annotations

import re
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy.orm import Session

from community.config import Settings
from community.db import utcnow
from community.errors import ApiError
from community.models import RateCounter

#: argon2id(argon2-cffi 的 PasswordHasher 缺省就是 argon2id,参数取它的 RFC 9106 低内存档)。
_HASHER = PasswordHasher()

#: 一个永远验不过的哈希:用户不存在 / 没设密码时也照样算一次,不让响应时间泄露「有没有这个人」。
_DUMMY_HASH = _HASHER.hash("mosael-community-dummy-password")

PASSWORD_MIN = 8
PASSWORD_MAX = 128

HANDLE_RE = re.compile(r"^[a-z0-9_]{3,24}$")
RESERVED_HANDLES = frozenset(
    {
        "official", "admin", "administrator", "moderator", "mosael", "api", "root", "system", "support", "help",
        "me", "settings", "login", "logout", "register", "device", "devices", "plugins", "workflows", "boards",
        "stats", "users", "user", "null", "undefined", "anonymous", "community",
    }
)

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")
CN_MOBILE_RE = re.compile(r"^1[3-9]\d{9}$")


def hash_password(password: str) -> str:
    check_password_shape(password)
    return _HASHER.hash(password)


def check_password_shape(password: str) -> None:
    if not isinstance(password, str) or not (PASSWORD_MIN <= len(password) <= PASSWORD_MAX):
        raise ApiError(422, "password_too_weak")


def verify_password(stored: str | None, password: str) -> bool:
    try:
        return _HASHER.verify(stored or _DUMMY_HASH, password or "") and stored is not None
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored: str) -> bool:
    return _HASHER.check_needs_rehash(stored)


def normalize_phone(raw: str) -> str:
    """→ E.164。11 位、1 开头的按中国大陆号码补 +86;带 + 的按国际号码认。认不出就报错。"""
    phone = re.sub(r"[\s-]", "", str(raw or ""))
    if phone.startswith("00"):
        phone = "+" + phone[2:]
    if CN_MOBILE_RE.match(phone):
        phone = "+86" + phone
    if not E164_RE.match(phone):
        raise ApiError(422, "invalid_phone")
    if phone.startswith("+86") and not CN_MOBILE_RE.match(phone[3:]):
        raise ApiError(422, "invalid_phone")
    return phone


def mask_phone(phone: str | None) -> str | None:
    if not phone:
        return None
    return f"{phone[:-8]}****{phone[-4:]}" if len(phone) > 8 else "****"


def normalize_handle(raw: str) -> str:
    handle = str(raw or "").strip().lower()
    if not HANDLE_RE.match(handle):
        raise ApiError(422, "handle_invalid")
    if handle in RESERVED_HANDLES:
        raise ApiError(422, "handle_reserved")
    return handle


# ---------------- 密码登录失败限速 ----------------


def _counter(db: Session, key: str) -> RateCounter:
    counter = db.get(RateCounter, key)
    if counter is None:
        counter = RateCounter(key=key, window_start=utcnow(), count=0)
        db.add(counter)
        db.flush()
    return counter


def check_login_allowed(db: Session, settings: Settings, *, account_key: str | None, ip: str) -> None:
    """登录前:这个账号 / 这个 IP 是不是还在锁定期里。"""
    now = utcnow()
    for key in filter(None, (f"pwd:acct:{account_key}" if account_key else None, f"pwd:ip:{ip}")):
        counter = db.get(RateCounter, key)
        if counter is not None and counter.locked_until is not None and counter.locked_until > now:
            minutes = max(1, int((counter.locked_until - now).total_seconds() // 60) + 1)
            raise ApiError(429, "login_locked", headers={"Retry-After": str(minutes * 60)}, minutes=minutes)


def record_login_failure(db: Session, settings: Settings, *, account_key: str | None, ip: str) -> None:
    """一次失败。账号维度:连续 N 次锁定一段时间(成功一次清零);IP 维度:一个窗口里失败 M 次锁到窗口结束。"""
    now = utcnow()
    if account_key:
        counter = _counter(db, f"pwd:acct:{account_key}")
        counter.count += 1
        if counter.count >= settings.password_account_max_failures:
            counter.locked_until = now + timedelta(seconds=settings.password_account_lock_seconds)
            counter.count = 0
    counter = _counter(db, f"pwd:ip:{ip}")
    window = timedelta(seconds=settings.password_ip_window_seconds)
    if counter.window_start + window < now:
        counter.window_start, counter.count = now, 0
    counter.count += 1
    if counter.count >= settings.password_ip_max_failures:
        counter.locked_until = counter.window_start + window


def record_login_success(db: Session, *, account_key: str) -> None:
    counter = db.get(RateCounter, f"pwd:acct:{account_key}")
    if counter is not None:
        counter.count = 0
        counter.locked_until = None


__all__ = [
    "RESERVED_HANDLES",
    "check_login_allowed",
    "check_password_shape",
    "hash_password",
    "mask_phone",
    "needs_rehash",
    "normalize_handle",
    "normalize_phone",
    "record_login_failure",
    "record_login_success",
    "verify_password",
]
