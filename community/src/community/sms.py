"""短信验证码:发、验,以及发送前的限速与(可选的)人机验证。

规则(ADR 0026 第 2 节):验证码 6 位、5 分钟有效、**只存哈希**、一个码最多试 5 次;同一号码 60 秒内不重发、
每天(滚动 24 小时)至多 10 条;同一 IP 每小时至多 20 条。新发一条,旧的那条立即作废。

发送器两种,由 `COMMUNITY_SMS_SENDER` 选:
- `tencent`:腾讯云短信 `SendSms`(官方 SDK 签名)。签名、模板、SdkAppId、SecretId/Key 全走环境变量。
- `console`:把验证码打到日志里,只给开发用;生产环境配置检查不让它上线。
"""

from __future__ import annotations

import hmac
import logging
import secrets
from datetime import timedelta
from typing import Protocol

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from community.config import Settings
from community.crypto import hmac_hex
from community.db import utcnow
from community.errors import ApiError
from community.logs import DEV_SMS_LOGGER, log_event
from community.models import SmsCode
from community.security import mask_phone

logger = logging.getLogger(__name__)

PURPOSES = ("login", "bind", "reset")


class SmsSendError(Exception):
    """短信没发出去。`code` 是对方给的错误码(不含号码与验证码)。"""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SmsSender(Protocol):
    def send(self, phone: str, code: str, *, purpose: str, ttl_minutes: int) -> None: ...


class ConsoleSender:
    """开发用:把验证码打进日志。"""

    def __init__(self) -> None:
        self.logger = logging.getLogger(DEV_SMS_LOGGER)

    def send(self, phone: str, code: str, *, purpose: str, ttl_minutes: int) -> None:
        self.logger.warning("[development SMS] to %s purpose=%s code=%s (valid %d min)", phone, purpose, code, ttl_minutes)


class TencentSender:
    """腾讯云短信 SendSms(API 2021-01-11)。模板变量按 `COMMUNITY_TENCENT_SMS_TEMPLATE_PARAMS` 的顺序填。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _client(self):  # pragma: no cover - 真的连腾讯云
        from tencentcloud.common import credential
        from tencentcloud.sms.v20210111 import sms_client

        cred = credential.Credential(self.settings.tencent_secret_id, self.settings.tencent_secret_key)
        return sms_client.SmsClient(cred, self.settings.tencent_sms_region)

    def build_request(self, phone: str, code: str, *, purpose: str, ttl_minutes: int):
        from tencentcloud.sms.v20210111 import models

        values = {"code": code, "minutes": str(ttl_minutes)}
        names = [name.strip() for name in self.settings.tencent_sms_template_params.split(",") if name.strip()]
        request = models.SendSmsRequest()
        request.SmsSdkAppId = self.settings.tencent_sms_sdk_app_id
        request.SignName = self.settings.tencent_sms_sign_name
        request.TemplateId = self.settings.template_for(purpose)
        request.TemplateParamSet = [values.get(name, "") for name in names]
        request.PhoneNumberSet = [phone]
        return request

    def send(self, phone: str, code: str, *, purpose: str, ttl_minutes: int) -> None:
        from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException

        request = self.build_request(phone, code, purpose=purpose, ttl_minutes=ttl_minutes)
        try:
            response = self._client().SendSms(request)
        except TencentCloudSDKException as exc:
            raise SmsSendError(str(getattr(exc, "code", "") or "sdk_error")) from exc
        statuses = list(getattr(response, "SendStatusSet", None) or [])
        if not statuses or getattr(statuses[0], "Code", "") != "Ok":
            raise SmsSendError(str(getattr(statuses[0], "Code", "") if statuses else "no_status"))


def make_sender(settings: Settings) -> SmsSender:
    return TencentSender(settings) if settings.sms_sender == "tencent" else ConsoleSender()


# ---------------- 人机验证(腾讯云验证码 / 天御),可选 ----------------


class CaptchaVerifier(Protocol):
    def verify(self, *, ticket: str, randstr: str, ip: str) -> bool: ...


class TencentCaptcha:
    """DescribeCaptchaResult(API 2019-07-22)。CaptchaCode == 1 为通过。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def verify(self, *, ticket: str, randstr: str, ip: str) -> bool:  # pragma: no cover - 真的连腾讯云
        from tencentcloud.captcha.v20190722 import captcha_client, models
        from tencentcloud.common import credential
        from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException

        request = models.DescribeCaptchaResultRequest()
        request.CaptchaType = 9
        request.Ticket = ticket
        request.Randstr = randstr
        request.UserIp = ip or "127.0.0.1"
        request.CaptchaAppId = int(self.settings.captcha_app_id)
        request.AppSecretKey = self.settings.captcha_app_secret_key
        cred = credential.Credential(self.settings.tencent_secret_id, self.settings.tencent_secret_key)
        try:
            response = captcha_client.CaptchaClient(cred, "").DescribeCaptchaResult(request)
        except TencentCloudSDKException:
            log_event(logger, "captcha verification call failed", logging.WARNING)
            return False
        return getattr(response, "CaptchaCode", None) == 1


def make_captcha(settings: Settings) -> CaptchaVerifier | None:
    return TencentCaptcha(settings) if settings.captcha_enabled else None


# ---------------- 发与验 ----------------


def _code_hash(settings: Settings, phone: str, purpose: str, code: str) -> str:
    return hmac_hex(settings.secret_key or "dev", "sms", phone, purpose, code)


def send_code(
    db: Session,
    settings: Settings,
    sender: SmsSender,
    *,
    phone: str,
    purpose: str,
    ip: str,
) -> None:
    """限速都过了才发。先记账、再发;发失败就把这一条删掉(不占用户的额度)。"""
    now = utcnow()
    latest = db.scalars(select(SmsCode).where(SmsCode.phone == phone).order_by(SmsCode.created_at.desc()).limit(1)).first()
    if latest is not None:
        waited = (now - latest.created_at).total_seconds()
        if waited < settings.sms_resend_seconds:
            seconds = int(settings.sms_resend_seconds - waited) + 1
            raise ApiError(429, "sms_too_frequent", headers={"Retry-After": str(seconds)}, seconds=seconds)
    per_phone = db.scalar(
        select(func.count()).select_from(SmsCode).where(SmsCode.phone == phone, SmsCode.created_at > now - timedelta(days=1))
    )
    if (per_phone or 0) >= settings.sms_daily_limit_per_phone:
        raise ApiError(429, "sms_daily_limit")
    if ip:
        per_ip = db.scalar(
            select(func.count()).select_from(SmsCode).where(SmsCode.ip == ip, SmsCode.created_at > now - timedelta(hours=1))
        )
        if (per_ip or 0) >= settings.sms_hourly_limit_per_ip:
            raise ApiError(429, "sms_ip_limit")

    # 开发环境可以钉一个固定码(COMMUNITY_DEV_SMS_CODE);别的环境配置校验不让它存在(见 config)。
    code = settings.dev_sms_code if settings.development and settings.dev_sms_code else f"{secrets.randbelow(1_000_000):06d}"
    # 新发一条,这个号码这个用途之前没用掉的全部作废。
    db.execute(
        update(SmsCode)
        .where(SmsCode.phone == phone, SmsCode.purpose == purpose, SmsCode.consumed_at.is_(None))
        .values(consumed_at=now)
    )
    record = SmsCode(
        phone=phone,
        purpose=purpose,
        code_hash=_code_hash(settings, phone, purpose, code),
        ip=ip[:64],
        created_at=now,
        expires_at=now + timedelta(seconds=settings.sms_code_ttl_seconds),
    )
    db.add(record)
    db.commit()
    try:
        sender.send(phone, code, purpose=purpose, ttl_minutes=max(1, settings.sms_code_ttl_seconds // 60))
    except SmsSendError as exc:
        db.delete(record)
        db.commit()
        log_event(logger, "sms send failed", logging.WARNING, phone=mask_phone(phone), provider_error=exc.code)
        raise ApiError(502, "sms_send_failed") from exc
    log_event(logger, "sms sent", phone=mask_phone(phone), purpose=purpose)


def verify_code(db: Session, settings: Settings, *, phone: str, purpose: str, code: str) -> None:
    """核对验证码。对了就用掉它;错了记一次,满 5 次这一条作废。调用方负责 commit。"""
    now = utcnow()
    record = db.scalars(
        select(SmsCode)
        .where(SmsCode.phone == phone, SmsCode.purpose == purpose)
        .order_by(SmsCode.created_at.desc())
        .limit(1)
        .with_for_update()
    ).first()
    if record is None:
        raise ApiError(400, "code_invalid")
    if record.consumed_at is not None:
        raise ApiError(400, "code_expired")
    if record.attempts >= settings.sms_max_attempts:
        raise ApiError(400, "code_attempts_exceeded")
    if record.expires_at <= now:
        raise ApiError(400, "code_expired")
    candidate = _code_hash(settings, phone, purpose, str(code or "").strip())
    if not hmac.compare_digest(candidate, record.code_hash):
        record.attempts += 1
        db.commit()
        if record.attempts >= settings.sms_max_attempts:
            raise ApiError(400, "code_attempts_exceeded")
        raise ApiError(400, "code_invalid")
    record.consumed_at = now


__all__ = [
    "CaptchaVerifier",
    "ConsoleSender",
    "PURPOSES",
    "SmsSendError",
    "SmsSender",
    "TencentCaptcha",
    "TencentSender",
    "make_captcha",
    "make_sender",
    "send_code",
    "verify_code",
]
