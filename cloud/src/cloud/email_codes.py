"""邮箱验证码的签发与校验 —— 所有阈值都在这里,并写清为什么是这些数。

设计约束:
- **只存哈希**,明文只出现在发出的邮件里;
- **一次性**,验过即写 `used_at`;
- **10 分钟 TTL**:够用户切到邮箱、等邮件到达,又短到值得暴力猜的窗口很小;
- **5 次错误作废**:6 位数字有 100 万种,5 次机会把在线猜中的概率压到 1/200000;
- **60 秒重发冷却 + 每邮箱 / 每 IP 每小时上限**:挡住"点爆发送按钮"和拿别人邮箱刷信;
- **注册与登录共用一套码**:purpose 区分,同一个码不能跨用途使用。
"""

from __future__ import annotations

import logging
import math
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from cloud.errors import CloudError
from cloud.mailer import CodeSender, mask_email
from cloud.models import CloudEmailCode, CloudUser, now
from cloud.security import email_code_digest, new_email_code

logger = logging.getLogger(__name__)

#: 6 位数字,允许前导 0。
CODE_LENGTH = 6
#: 10 分钟。短于常见的"切到邮箱再回来"要更久,长于这会把可猜窗口放大。
CODE_TTL_SECONDS = 10 * 60
#: 同一枚码最多验错 5 次。到上限即作废,逼用户重新发码 —— 只靠 TTL 不够。
CODE_MAX_ATTEMPTS = 5
#: 同一邮箱 + 同一用途 60 秒内只能发一次。低于 60 秒用户很容易连点两下。
RESEND_COOLDOWN_SECONDS = 60
#: 每邮箱每用途每小时最多 5 封。正常人一次注册 / 登录用不到 5 封;超过就是想刷。
EMAIL_HOURLY_LIMIT = 5
#: 每 IP 每小时最多 20 封。比单邮箱宽,是因为同一个 NAT 后面可能坐着多个人;
#: 单邮箱上限才是挡"轰炸某个收件箱"的那道。
IP_HOURLY_LIMIT = 20

PURPOSES = frozenset({"signup", "login"})


def issue_code(
    db: Session,
    *,
    email: str,
    purpose: str,
    request_ip: str,
    sender: CodeSender,
) -> None:
    """签发并投递一枚验证码。

    登录用途**先落一行,再决定发不发**:未注册邮箱也占一次配额,这样"这个邮箱存不存在"
    不会从冷却 / 限流行为里漏出去。注册用途对已存在的邮箱直接 409(注册页本来就会说)。
    """
    if purpose not in PURPOSES:
        raise ValueError(f"unknown code purpose: {purpose}")

    # 先确认发信通道可用:没配置时无论邮箱是否注册都回同一个 503,不泄露注册状态,
    # 也不会留下永远送不到的码。
    sender.ensure_ready()

    current = now()
    user = db.scalar(select(CloudUser).where(CloudUser.email == email))
    if purpose == "signup" and user is not None:
        raise CloudError(409, "email_taken")

    _enforce_resend_cooldown(db, email=email, purpose=purpose, current=current)
    _enforce_hourly_limits(db, email=email, purpose=purpose, request_ip=request_ip, current=current)

    code = new_email_code()
    row = CloudEmailCode(
        email=email,
        purpose=purpose,
        code_hash=email_code_digest(email, purpose, code),
        request_ip=request_ip,
        created_at=current,
        expires_at=current + timedelta(seconds=CODE_TTL_SECONDS),
    )
    db.add(row)
    db.commit()

    if purpose == "login" and user is None:
        # 未知邮箱不投递(没有账号可登录),但响应 / 配额与已注册邮箱完全一致 ——
        # 枚举防护靠的就是这两条路径不可区分。
        # 官方账号**不在这里**:它的邮箱由部署配置成真实拥有的地址,验证码正常投递、
        # 正常受上面那几条冷却 / 每小时上限约束(没有官方号后门)。
        logger.info(
            "login code requested for an unknown address (%s); response kept identical",
            mask_email(email),
        )
        return

    try:
        sender.send_code(email=email, purpose=purpose, code=code)
    except Exception:
        # 没发出去的码不该留着:用户收不到,它只会占着冷却和配额。
        db.delete(row)
        db.commit()
        raise

    # 日志只写脱敏收件人,不写码。
    logger.info("sent %s code to %s", purpose, mask_email(email))


def consume_code(db: Session, *, email: str, purpose: str, code: str) -> None:
    """校验并烧掉最新一枚码。

    失败分类要明确:不存在 / 错 / 过期 / 已用 / 错太多次,各给各的码,前端才能说人话。
    """
    current = now()
    row = db.scalar(
        select(CloudEmailCode)
        .where(CloudEmailCode.email == email, CloudEmailCode.purpose == purpose)
        .order_by(CloudEmailCode.created_at.desc())
        .limit(1)
    )
    if row is None:
        raise CloudError(400, "email_code_invalid")
    if row.used_at is not None:
        raise CloudError(400, "email_code_used")
    if row.expires_at <= current:
        raise CloudError(400, "email_code_expired")
    if row.attempts >= CODE_MAX_ATTEMPTS:
        raise CloudError(400, "email_code_attempts_exhausted")

    expected = email_code_digest(email, purpose, code)
    if not secrets.compare_digest(row.code_hash, expected):
        row.attempts += 1
        db.commit()
        if row.attempts >= CODE_MAX_ATTEMPTS:
            raise CloudError(400, "email_code_attempts_exhausted")
        raise CloudError(400, "email_code_invalid")

    row.used_at = current
    db.commit()


def _enforce_resend_cooldown(db: Session, *, email: str, purpose: str, current) -> None:
    last = db.scalar(
        select(CloudEmailCode.created_at)
        .where(CloudEmailCode.email == email, CloudEmailCode.purpose == purpose)
        .order_by(CloudEmailCode.created_at.desc())
        .limit(1)
    )
    if last is None:
        return
    ready_at = last + timedelta(seconds=RESEND_COOLDOWN_SECONDS)
    if ready_at > current:
        retry_after = max(1, math.ceil((ready_at - current).total_seconds()))
        raise CloudError(429, "email_code_cooldown", seconds=retry_after)


def _enforce_hourly_limits(
    db: Session,
    *,
    email: str,
    purpose: str,
    request_ip: str,
    current,
) -> None:
    since = current - timedelta(hours=1)
    per_email = db.scalar(
        select(func.count())
        .select_from(CloudEmailCode)
        .where(
            CloudEmailCode.email == email,
            CloudEmailCode.purpose == purpose,
            CloudEmailCode.created_at >= since,
        )
    )
    if per_email is not None and per_email >= EMAIL_HOURLY_LIMIT:
        raise CloudError(429, "too_many_requests")

    if not request_ip:
        return
    per_ip = db.scalar(
        select(func.count())
        .select_from(CloudEmailCode)
        .where(CloudEmailCode.request_ip == request_ip, CloudEmailCode.created_at >= since)
    )
    if per_ip is not None and per_ip >= IP_HOURLY_LIMIT:
        raise CloudError(429, "too_many_requests")
