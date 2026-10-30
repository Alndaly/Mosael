"""MFA 的数据库动作:登录票据、TOTP / 恢复码校验、恢复码轮换。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from cloud.config import CloudConfig
from cloud.mfa import (
    new_recovery_codes,
    open_secret,
    recovery_digest,
    verify_totp,
)
from cloud.models import CloudMfaRecoveryCode, CloudMfaTicket, CloudUser, now
from cloud.security import new_token, token_digest


def enabled(user: CloudUser) -> bool:
    return bool(user.mfa_enabled_at and user.mfa_totp_secret_encrypted)


def create_ticket(db: Session, user: CloudUser, config: CloudConfig) -> str:
    raw = new_token()
    db.add(
        CloudMfaTicket(
            ticket_hash=token_digest(raw),
            user_id=user.id,
            expires_at=now() + timedelta(seconds=config.mfa_ticket_ttl_seconds),
        )
    )
    db.flush()
    return raw


def ticket_for(db: Session, raw: str) -> CloudMfaTicket | None:
    return db.scalar(select(CloudMfaTicket).where(CloudMfaTicket.ticket_hash == token_digest(raw)))


def verify_code(db: Session, user: CloudUser, config: CloudConfig, code: str) -> str | None:
    """成功返回 `totp` / `recovery`,失败 None。调用方负责提交事务。"""
    digest = recovery_digest(code)
    recovery = db.scalar(
        select(CloudMfaRecoveryCode).where(
            CloudMfaRecoveryCode.user_id == user.id,
            CloudMfaRecoveryCode.code_hash == digest,
            CloudMfaRecoveryCode.used_at.is_(None),
        )
    )
    if recovery is not None:
        consumed = db.execute(
            update(CloudMfaRecoveryCode)
            .where(CloudMfaRecoveryCode.id == recovery.id, CloudMfaRecoveryCode.used_at.is_(None))
            .values(used_at=now())
        )
        return "recovery" if consumed.rowcount == 1 else None

    if not user.mfa_totp_secret_encrypted:
        return None
    secret = open_secret(config, user.mfa_totp_secret_encrypted)
    step = verify_totp(secret, code)
    if step is None:
        return None
    #: 同一个时间步只能成功一次,防止 30 秒内重放同一个码。用条件 UPDATE 做原子占位,
    #: 两个并发请求不会同时读到旧的 last_used_step。
    claimed = db.execute(
        update(CloudUser)
        .where(
            CloudUser.id == user.id,
            (CloudUser.mfa_last_used_step.is_(None)) | (CloudUser.mfa_last_used_step < step),
        )
        .values(mfa_last_used_step=step)
    )
    if claimed.rowcount != 1:
        return None
    user.mfa_last_used_step = step
    return "totp"


def recovery_codes_remaining(db: Session, user_id: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(CloudMfaRecoveryCode)
            .where(CloudMfaRecoveryCode.user_id == user_id, CloudMfaRecoveryCode.used_at.is_(None))
        )
        or 0
    )


def replace_recovery_codes(db: Session, user: CloudUser) -> list[str]:
    codes = new_recovery_codes()
    db.execute(delete(CloudMfaRecoveryCode).where(CloudMfaRecoveryCode.user_id == user.id))
    for code in codes:
        db.add(CloudMfaRecoveryCode(user_id=user.id, code_hash=recovery_digest(code)))
    return codes


def clear(db: Session, user: CloudUser) -> None:
    db.execute(delete(CloudMfaRecoveryCode).where(CloudMfaRecoveryCode.user_id == user.id))
    user.mfa_totp_secret_encrypted = None
    user.mfa_pending_secret_encrypted = None
    user.mfa_pending_expires_at = None
    user.mfa_enabled_at = None
    user.mfa_last_used_step = None
