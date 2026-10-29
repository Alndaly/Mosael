"""手机短信验证码:签发、冷却、校验。

阈值与邮箱验证码共用 **10 分钟 TTL / 5 次错误作废 / 60 秒重发冷却 / 每 IP 每小时 20 条**;
单手机号每小时 5 条。短信登录即注册:号码没有账号时,验码成功后新建一个手机号账号。
"""

from __future__ import annotations

import logging
import math
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud.email_codes import (
    CODE_MAX_ATTEMPTS,
    CODE_TTL_SECONDS,
    IP_HOURLY_LIMIT,
    RESEND_COOLDOWN_SECONDS,
)
from cloud.errors import CloudError
from cloud.models import CloudPhoneCode, now
from cloud.phone import mask_phone
from cloud.security import new_email_code, phone_code_digest
from cloud.sms import PhoneCodeSender

logger = logging.getLogger(__name__)

#: 单手机号每小时最多 5 条。正常人一次登录用不到 5 条。
PHONE_HOURLY_LIMIT = 5
PURPOSES = frozenset({"login"})


def issue_phone_code(
    db: Session,
    *,
    phone: str,
    purpose: str,
    request_ip: str,
    sender: PhoneCodeSender,
) -> None:
    if purpose not in PURPOSES:
        raise ValueError(f"unknown phone code purpose: {purpose}")
    sender.ensure_ready()
    current = now()
    _enforce_cooldown(db, phone=phone, purpose=purpose, current=current)
    _enforce_limits(db, phone=phone, purpose=purpose, request_ip=request_ip, current=current)
    code = new_email_code()
    row = CloudPhoneCode(
        phone=phone,
        purpose=purpose,
        code_hash=phone_code_digest(phone, purpose, code),
        request_ip=request_ip,
        created_at=current,
        expires_at=current + timedelta(seconds=CODE_TTL_SECONDS),
    )
    db.add(row)
    db.commit()
    try:
        sender.send_code(phone=phone, purpose=purpose, code=code)
    except Exception:
        db.delete(row)
        db.commit()
        raise
    logger.info("sent %s code to %s", purpose, mask_phone(phone))


def consume_phone_code(db: Session, *, phone: str, purpose: str, code: str) -> None:
    current = now()
    row = db.scalar(
        select(CloudPhoneCode)
        .where(CloudPhoneCode.phone == phone, CloudPhoneCode.purpose == purpose)
        .order_by(CloudPhoneCode.created_at.desc())
        .limit(1)
    )
    if row is None:
        raise CloudError(400, "phone_code_invalid")
    if row.used_at is not None:
        raise CloudError(400, "phone_code_used")
    if row.expires_at <= current:
        raise CloudError(400, "phone_code_expired")
    if row.attempts >= CODE_MAX_ATTEMPTS:
        raise CloudError(400, "phone_code_attempts_exhausted")
    expected = phone_code_digest(phone, purpose, code)
    if not secrets.compare_digest(row.code_hash, expected):
        row.attempts += 1
        db.commit()
        if row.attempts >= CODE_MAX_ATTEMPTS:
            raise CloudError(400, "phone_code_attempts_exhausted")
        raise CloudError(400, "phone_code_invalid")
    row.used_at = current
    db.commit()


def _enforce_cooldown(db: Session, *, phone: str, purpose: str, current) -> None:
    last = db.scalar(
        select(CloudPhoneCode.created_at)
        .where(CloudPhoneCode.phone == phone, CloudPhoneCode.purpose == purpose)
        .order_by(CloudPhoneCode.created_at.desc())
        .limit(1)
    )
    if last is None:
        return
    ready_at = last + timedelta(seconds=RESEND_COOLDOWN_SECONDS)
    if ready_at > current:
        retry_after = max(1, math.ceil((ready_at - current).total_seconds()))
        raise CloudError(429, "phone_code_cooldown", seconds=retry_after)


def _enforce_limits(db: Session, *, phone: str, purpose: str, request_ip: str, current) -> None:
    since = current - timedelta(hours=1)
    per_phone = db.scalar(
        select(func.count())
        .select_from(CloudPhoneCode)
        .where(
            CloudPhoneCode.phone == phone,
            CloudPhoneCode.purpose == purpose,
            CloudPhoneCode.created_at >= since,
        )
    )
    if per_phone is not None and per_phone >= PHONE_HOURLY_LIMIT:
        raise CloudError(429, "too_many_requests")
    if not request_ip:
        return
    per_ip = db.scalar(
        select(func.count())
        .select_from(CloudPhoneCode)
        .where(CloudPhoneCode.request_ip == request_ip, CloudPhoneCode.created_at >= since)
    )
    if per_ip is not None and per_ip >= IP_HOURLY_LIMIT:
        raise CloudError(429, "too_many_requests")
