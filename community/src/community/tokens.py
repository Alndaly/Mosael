"""令牌:短命的访问令牌(EdDSA JWT,15 分钟)+ 轮换的刷新令牌(ADR 0026 第 3 节)。

- 访问令牌的载荷只有 `sub`(用户 id)、`sid`(会话 id)、`role`,外加 `iat` / `exp`。
- 刷新令牌是 256 位随机串,**库里只存 sha256**,属于一个会话。每用一次就换一个新的;
  已经换掉的旧令牌再被拿来用 = 被盗,**整个会话吊销** —— 除非是在被换掉后的 20 秒宽限期内
  (几个并发请求同时刷新),那时返回**同一对**新令牌。
- 同一对新令牌是怎么「再给一遍」的:新刷新令牌由旧令牌派生(`crypto.derive_token`),不用存明文;
  访问令牌用的是 Ed25519 —— 签名是确定的,同样的载荷签出同样的串,所以记下签发时间和角色就够。
- 会话滑动 30 天、绝对上限 90 天。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from community.config import Settings
from community.crypto import derive_token, random_token, sha256_hex
from community.db import utcnow
from community.errors import ApiError
from community.logs import log_event
from community.models import AuthSession, RefreshToken, User

logger = logging.getLogger(__name__)

ALGORITHM = "EdDSA"
SESSION_WEB = "web"
SESSION_APP = "app"


class KeyRing:
    """签访问令牌的那把 Ed25519 私钥。"""

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self.private_key = private_key
        self.public_key: Ed25519PublicKey = private_key.public_key()

    @classmethod
    def from_settings(cls, settings: Settings) -> "KeyRing":
        pem = settings.jwt_private_key
        if not pem and settings.jwt_private_key_file:
            pem = Path(settings.jwt_private_key_file).read_text(encoding="utf-8")
        if not pem:
            if settings.production:
                raise RuntimeError("COMMUNITY_JWT_PRIVATE_KEY is required in production")
            if settings.development:
                return cls(dev_key(Path(settings.data_dir) / DEV_KEY_NAME))
            # 测试:每次一把临时的。
            return cls(Ed25519PrivateKey.generate())
        key = serialization.load_pem_private_key(pem.replace("\\n", "\n").encode("utf-8"), password=None)
        if not isinstance(key, Ed25519PrivateKey):
            raise RuntimeError("COMMUNITY_JWT_PRIVATE_KEY must be an Ed25519 private key")
        return cls(key)


#: 开发环境自动生成的签名密钥放在数据目录里的这个文件(权限 600)。
DEV_KEY_NAME = "dev-jwt-key.pem"


def dev_key(path: Path) -> Ed25519PrivateKey:
    """开发用的签名密钥:第一次启动时生成到数据目录,之后一直用它 —— 重启不把人踢下线。"""
    if path.is_file():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if isinstance(key, Ed25519PrivateKey):
            return key
    key = Ed25519PrivateKey.generate()
    path.parent.mkdir(parents=True, exist_ok=True)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(pem)
    log_event(logger, "generated a development JWT key", logging.WARNING, path=str(path))
    return key


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    expires_in: int
    refresh_token: str
    session: AuthSession
    user: User


def encode_access(keys: KeyRing, *, user_id: str, session_id: str, role: str, iat: int, ttl: int) -> str:
    return jwt.encode(
        {"sub": user_id, "sid": session_id, "role": role, "iat": iat, "exp": iat + ttl},
        keys.private_key,
        algorithm=ALGORITHM,
    )


def decode_access(keys: KeyRing, token: str) -> dict:
    try:
        return jwt.decode(token, keys.public_key, algorithms=[ALGORITHM], options={"require": ["sub", "sid", "exp"]})
    except jwt.ExpiredSignatureError as exc:
        raise ApiError(401, "token_expired") from exc
    except jwt.InvalidTokenError as exc:
        raise ApiError(401, "unauthorized") from exc


def _hash(raw: str) -> str:
    return sha256_hex(raw)


def _issue_refresh(db: Session, session: AuthSession, raw: str, *, role: str, iat: int) -> RefreshToken:
    token = RefreshToken(session_id=session.id, token_hash=_hash(raw), pair_iat=iat, pair_role=role)
    db.add(token)
    db.flush()
    return token


def start_session(
    db: Session,
    settings: Settings,
    keys: KeyRing,
    user: User,
    *,
    kind: str,
    device_name: str = "",
    ip: str = "",
    user_agent: str = "",
) -> TokenPair:
    """登录成功:开一个会话,发第一对令牌。"""
    now = utcnow()
    session = AuthSession(
        user_id=user.id,
        kind=kind,
        device_name=device_name[:120],
        ip=ip[:64],
        user_agent=user_agent[:300],
        created_at=now,
        last_used_at=now,
        expires_at=now + timedelta(days=settings.refresh_idle_days),
        absolute_expires_at=now + timedelta(days=settings.refresh_absolute_days),
    )
    db.add(session)
    db.flush()
    raw = random_token(32)
    iat = int(now.timestamp())
    _issue_refresh(db, session, raw, role=user.role, iat=iat)
    access = encode_access(keys, user_id=user.id, session_id=session.id, role=user.role, iat=iat, ttl=settings.access_token_ttl_seconds)
    log_event(logger, "session started", user_id=user.id, session_id=session.id, kind=kind)
    return TokenPair(access, settings.access_token_ttl_seconds, raw, session, user)


def _session_alive(session: AuthSession, now: datetime) -> bool:
    return session.revoked_at is None and session.expires_at > now and session.absolute_expires_at > now


def revoke_session(db: Session, session: AuthSession, reason: str) -> None:
    if session.revoked_at is None:
        session.revoked_at = utcnow()
        session.revoke_reason = reason
        log_event(logger, "session revoked", user_id=session.user_id, session_id=session.id, reason=reason)


def revoke_all(db: Session, user_id: str, reason: str, *, except_session_id: str | None = None) -> int:
    stmt = (
        update(AuthSession)
        .where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=utcnow(), revoke_reason=reason)
    )
    if except_session_id:
        stmt = stmt.where(AuthSession.id != except_session_id)
    count = db.execute(stmt).rowcount or 0
    log_event(logger, "sessions revoked", user_id=user_id, reason=reason, count=count)
    return count


def rotate(db: Session, settings: Settings, keys: KeyRing, raw: str, *, ip: str = "", user_agent: str = "") -> TokenPair:
    """用一枚刷新令牌换一对新的。见模块说明里的轮换、重用检测与宽限期。"""
    if not raw:
        raise ApiError(401, "refresh_missing")
    token = db.scalars(select(RefreshToken).where(RefreshToken.token_hash == _hash(raw)).with_for_update()).first()
    if token is None:
        raise ApiError(401, "refresh_invalid")
    session = db.get(AuthSession, token.session_id)
    now = utcnow()
    if session is None or not _session_alive(session, now):
        raise ApiError(401, "session_expired")
    user = db.get(User, session.user_id)
    if user is None or user.status != "active":
        revoke_session(db, session, "banned")
        db.commit()
        raise ApiError(401, "session_expired")

    if token.rotated_at is not None:
        # 已经换掉的旧令牌又来了。宽限期内:并发刷新,原样再给一遍那对新令牌;过了宽限期:视为被盗。
        within_grace = (now - token.rotated_at).total_seconds() <= settings.refresh_grace_seconds
        successor = db.get(RefreshToken, token.successor_id) if token.successor_id else None
        if within_grace and successor is not None:
            successor_raw = derive_token(settings.secret_key or "dev", "refresh-successor", raw)
            if _hash(successor_raw) == successor.token_hash:
                access = encode_access(
                    keys,
                    user_id=user.id,
                    session_id=session.id,
                    role=successor.pair_role,
                    iat=successor.pair_iat,
                    ttl=settings.access_token_ttl_seconds,
                )
                remaining = max(1, successor.pair_iat + settings.access_token_ttl_seconds - int(now.timestamp()))
                return TokenPair(access, remaining, successor_raw, session, user)
        revoke_session(db, session, "refresh_reused")
        db.commit()
        log_event(logger, "refresh token reuse detected", logging.WARNING, user_id=user.id, session_id=session.id)
        raise ApiError(401, "refresh_reused")

    successor_raw = derive_token(settings.secret_key or "dev", "refresh-successor", raw)
    iat = int(now.timestamp())
    successor = _issue_refresh(db, session, successor_raw, role=user.role, iat=iat)
    token.rotated_at = now
    token.successor_id = successor.id
    session.last_used_at = now
    session.expires_at = min(now + timedelta(days=settings.refresh_idle_days), session.absolute_expires_at)
    if ip:
        session.ip = ip[:64]
    if user_agent:
        session.user_agent = user_agent[:300]
    access = encode_access(keys, user_id=user.id, session_id=session.id, role=user.role, iat=iat, ttl=settings.access_token_ttl_seconds)
    return TokenPair(access, settings.access_token_ttl_seconds, successor_raw, session, user)


def session_for_refresh(db: Session, raw: str) -> AuthSession | None:
    token = db.scalars(select(RefreshToken).where(RefreshToken.token_hash == _hash(raw))).first()
    return db.get(AuthSession, token.session_id) if token else None


__all__ = [
    "KeyRing",
    "SESSION_APP",
    "SESSION_WEB",
    "TokenPair",
    "decode_access",
    "encode_access",
    "revoke_all",
    "revoke_session",
    "rotate",
    "session_for_refresh",
    "start_session",
]
