"""可选 TOTP 双因素:设置、启停、恢复码与登录第二步。"""

from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Response
from sqlalchemy import update
from pydantic import BaseModel, Field

from cloud.api.auth import open_session
from cloud.api.deps import CurrentConfig, CurrentUser, DbSession
from cloud.domain import mfa as mfa_domain
from cloud.domain.identity import account_user
from cloud.errors import CloudError
from cloud.mfa import (
    new_totp_secret,
    open_secret,
    otpauth_uri,
    seal_secret,
    verify_totp,
)
from cloud.models import CloudMfaTicket, CloudUser, now

router = APIRouter(tags=["mfa"])
SETUP_TTL = timedelta(minutes=10)


class MfaCodeIn(BaseModel):
    code: str = Field(min_length=1, max_length=64)


class MfaVerifyIn(MfaCodeIn):
    ticket: str = Field(min_length=1, max_length=512)


def _label(user: CloudUser) -> str:
    return user.email or user.phone or user.id


@router.get("/mfa")
def mfa_status(user: CurrentUser, db: DbSession) -> dict[str, object]:
    return {
        "enabled": mfa_domain.enabled(user),
        "recovery_codes_remaining": mfa_domain.recovery_codes_remaining(db, user.id),
    }


@router.post("/mfa/setup")
def mfa_setup(user: CurrentUser, db: DbSession, config: CurrentConfig) -> dict[str, object]:
    if not config.mfa_key:
        raise CloudError(503, "mfa_not_configured")
    if mfa_domain.enabled(user):
        raise CloudError(409, "mfa_already_enabled")
    secret = new_totp_secret()
    user.mfa_pending_secret_encrypted = seal_secret(config, secret)
    user.mfa_pending_expires_at = now() + SETUP_TTL
    db.commit()
    return {"secret": secret, "otpauth_uri": otpauth_uri(account=_label(user), secret=secret)}


@router.post("/mfa/enable")
def mfa_enable(body: MfaCodeIn, user: CurrentUser, db: DbSession, config: CurrentConfig) -> dict[str, object]:
    if mfa_domain.enabled(user):
        raise CloudError(409, "mfa_already_enabled")
    if not user.mfa_pending_secret_encrypted or not user.mfa_pending_expires_at or user.mfa_pending_expires_at <= now():
        raise CloudError(400, "mfa_setup_required")
    secret = open_secret(config, user.mfa_pending_secret_encrypted)
    step = verify_totp(secret, body.code)
    if step is None:
        raise CloudError(401, "mfa_code_invalid")
    user.mfa_totp_secret_encrypted = seal_secret(config, secret)
    user.mfa_enabled_at = now()
    user.mfa_last_used_step = step
    user.mfa_pending_secret_encrypted = None
    user.mfa_pending_expires_at = None
    codes = mfa_domain.replace_recovery_codes(db, user)
    db.commit()
    return {"enabled": True, "recovery_codes": codes}


@router.post("/mfa/disable")
def mfa_disable(body: MfaCodeIn, user: CurrentUser, db: DbSession, config: CurrentConfig) -> dict[str, object]:
    if not mfa_domain.enabled(user):
        raise CloudError(400, "mfa_not_enabled")
    if mfa_domain.verify_code(db, user, config, body.code) is None:
        db.rollback()
        raise CloudError(401, "mfa_code_invalid")
    mfa_domain.clear(db, user)
    db.commit()
    return {"enabled": False}


@router.post("/mfa/recovery-codes")
def mfa_recovery_codes(
    body: MfaCodeIn, user: CurrentUser, db: DbSession, config: CurrentConfig
) -> dict[str, object]:
    if not mfa_domain.enabled(user):
        raise CloudError(400, "mfa_not_enabled")
    if mfa_domain.verify_code(db, user, config, body.code) is None:
        db.rollback()
        raise CloudError(401, "mfa_code_invalid")
    codes = mfa_domain.replace_recovery_codes(db, user)
    db.commit()
    return {"recovery_codes": codes}


@router.post("/mfa/verify")
def mfa_verify(
    body: MfaVerifyIn, db: DbSession, config: CurrentConfig, response: Response
) -> dict[str, object]:
    ticket = mfa_domain.ticket_for(db, body.ticket)
    if ticket is None or ticket.used_at is not None or ticket.expires_at <= now():
        raise CloudError(401, "mfa_ticket_invalid")
    if ticket.attempts >= config.mfa_max_attempts:
        raise CloudError(429, "mfa_attempts_exceeded")
    user = db.get(CloudUser, ticket.user_id)
    if user is None:
        raise CloudError(401, "mfa_ticket_invalid")
    if mfa_domain.verify_code(db, user, config, body.code) is None:
        ticket.attempts += 1
        db.commit()
        if ticket.attempts >= config.mfa_max_attempts:
            raise CloudError(429, "mfa_attempts_exceeded")
        raise CloudError(401, "mfa_code_invalid")
    consumed = db.execute(
        update(CloudMfaTicket)
        .where(CloudMfaTicket.id == ticket.id, CloudMfaTicket.used_at.is_(None))
        .values(used_at=now())
    )
    if consumed.rowcount != 1:
        db.rollback()
        raise CloudError(401, "mfa_ticket_invalid")
    db.commit()
    open_session(db, config, user, response)
    return {"user": account_user(user)}
