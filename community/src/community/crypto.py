"""几样小的密码学工具:哈希、HMAC、签名的短令牌、随机串。都用标准库。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hmac_hex(key: str, *parts: str) -> str:
    return hmac.new(key.encode("utf-8"), "\x1f".join(parts).encode("utf-8"), hashlib.sha256).hexdigest()


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def random_token(nbytes: int = 32) -> str:
    """256 位随机串(URL 安全)。"""
    return secrets.token_urlsafe(nbytes)


def derive_token(key: str, purpose: str, seed: str) -> str:
    """由 `seed` 确定地派生出另一枚 256 位令牌。没有 key 和 seed 算不出来。

    刷新令牌的宽限期用它:旧令牌在被换掉后 20 秒内再来,要返回**同一枚**新令牌,而库里只存哈希 ——
    新令牌由旧令牌派生,就不必把明文存下来。
    """
    digest = hmac.new(key.encode("utf-8"), f"{purpose}\x1f{seed}".encode("utf-8"), hashlib.sha256).digest()
    return b64url(digest)


def sign_payload(key: str, payload: dict[str, Any], ttl_seconds: int) -> str:
    """签一个带过期时间的小载荷:`base64(json).签名`。"""
    body = dict(payload, e=int(time.time()) + ttl_seconds)
    encoded = b64url(json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8"))
    return f"{encoded}.{hmac_hex(key, 'signed-payload', encoded)}"


def verify_payload(key: str, token: str) -> dict[str, Any] | None:
    try:
        encoded, signature = token.rsplit(".", 1)
    except ValueError:
        return None
    if not hmac.compare_digest(signature, hmac_hex(key, "signed-payload", encoded)):
        return None
    try:
        body = json.loads(b64url_decode(encoded))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(body, dict) or int(body.get("e", 0)) < time.time():
        return None
    return body


__all__ = [
    "b64url",
    "b64url_decode",
    "derive_token",
    "hmac_hex",
    "random_token",
    "sha256_hex",
    "sign_payload",
    "verify_payload",
]
