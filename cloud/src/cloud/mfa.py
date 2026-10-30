"""可选 TOTP 双因素:secret 加密、时间码校验、恢复码生成。

TOTP 用 RFC 6238 的标准参数(SHA-1 / 6 位 / 30 秒);不引入第三方库,避免为了一个
100 行的算法多一个运行时依赖。secret 用独立的 `CLOUD_MFA_KEY` 加密,不复用上游 Key 的
`CLOUD_CHANNEL_KEY` —— 两把钥匙的用途和轮换节奏不同。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

from cryptography.fernet import Fernet, InvalidToken

from cloud.config import CloudConfig
from cloud.errors import CloudError

RECOVERY_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
RECOVERY_COUNT = 10
RECOVERY_LENGTH = 10
TOTP_PERIOD = 30
TOTP_DIGITS = 6
TOTP_WINDOW = 1


def new_fernet_key() -> str:
    """生成一把 `CLOUD_MFA_KEY`。换钥匙后已开启 MFA 的账号无法验证,需要先关闭/重设。"""
    return Fernet.generate_key().decode("ascii")


def new_totp_secret() -> str:
    """160 位随机 secret,base32 不带 padding(认证器 App 都接受)。"""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    padded = secret.strip().upper()
    padded += "=" * ((8 - len(padded) % 8) % 8)
    try:
        return base64.b32decode(padded, casefold=True)
    except Exception as exc:
        raise CloudError(503, "mfa_not_configured") from exc


def totp_code(secret: str, *, step: int) -> str:
    digest = hmac.new(_decode_secret(secret), struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10**TOTP_DIGITS:0{TOTP_DIGITS}d}"


def verify_totp(secret: str, code: str, *, at: float | None = None) -> int | None:
    """校验 6 位码,允许前后各一个时间步;成功返回命中的 step,失败 None。"""
    normalized = "".join(ch for ch in code if ch.isdigit())
    if len(normalized) != TOTP_DIGITS:
        return None
    current = int((time.time() if at is None else at) // TOTP_PERIOD)
    for step in range(current - TOTP_WINDOW, current + TOTP_WINDOW + 1):
        if hmac.compare_digest(totp_code(secret, step=step), normalized):
            return step
    return None


def otpauth_uri(*, account: str, secret: str) -> str:
    label = quote(f"MosaelCloud:{account}", safe="")
    query = urlencode(
        {
            "secret": secret,
            "issuer": "MosaelCloud",
            "algorithm": "SHA1",
            "digits": TOTP_DIGITS,
            "period": TOTP_PERIOD,
        }
    )
    return f"otpauth://totp/{label}?{query}"


def new_recovery_codes(count: int = RECOVERY_COUNT) -> list[str]:
    """高熵一次性恢复码;显示时分成 5-5,存储前去掉分隔符。"""
    raw = [
        "".join(secrets.choice(RECOVERY_ALPHABET) for _ in range(RECOVERY_LENGTH))
        for _ in range(count)
    ]
    return [f"{code[:5]}-{code[5:]}" for code in raw]


def normalize_recovery_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def recovery_digest(code: str) -> str:
    return hashlib.sha256(normalize_recovery_code(code).encode("utf-8")).hexdigest()


def _fernet(config: CloudConfig) -> Fernet:
    if not config.mfa_key:
        raise CloudError(503, "mfa_not_configured")
    try:
        return Fernet(config.mfa_key.encode("ascii"))
    except (ValueError, TypeError) as exc:
        raise CloudError(503, "mfa_not_configured") from exc


def seal_secret(config: CloudConfig, secret: str) -> str:
    return _fernet(config).encrypt(secret.encode("utf-8")).decode("ascii")


def open_secret(config: CloudConfig, sealed: str) -> str:
    try:
        return _fernet(config).decrypt(sealed.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise CloudError(503, "mfa_not_configured") from exc
