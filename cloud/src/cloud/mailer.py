"""发信:把 6 位验证码交给 SMTP。

**没有配置就明确报错**,绝不"假装发了":开发与测试拿不到邮件时,应该看到
`mail_not_configured`,而不是一个成功响应后再也等不到码。

测试不从这条路真发:它们注入 `CodeSender` 的假实现(见 `tests/conftest.py`)。真机验证时把
`CLOUD_SMTP_HOST` 指向 Mailpit(`localhost:1025`)或任意 SMTP 收件箱。

**日志里不出现完整验证码**,邮箱也只出现脱敏形式。
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import Protocol

from cloud.config import CloudConfig
from cloud.errors import CloudError

logger = logging.getLogger(__name__)

#: 一次发信最多等多久。请求线程不该被一个连不上的 SMTP 服务器拖住。
SMTP_TIMEOUT_SECONDS = 10


class CodeSender(Protocol):
    """发一封验证码邮件。测试注入假实现,生产用 `SmtpCodeSender`。"""

    def ensure_ready(self) -> None:
        """发信通道是否可用。不可用就抛 `mail_not_configured`,不要等走到"发"才发现。"""
        ...

    def send_code(self, *, email: str, purpose: str, code: str) -> None: ...


def mask_email(email: str) -> str:
    """`alice@example.com` → `a***@example.com`。日志里只配出现这个。"""
    local, separator, domain = email.partition("@")
    if not separator or not local or not domain:
        return "***"
    return f"{local[:1]}***@{domain}"


def _subject(purpose: str) -> str:
    action = "注册" if purpose == "signup" else "登录"
    verb = "sign-up" if purpose == "signup" else "sign-in"
    return f"MosaelCloud {action}验证码 / Your MosaelCloud {verb} code"


def _body(purpose: str, code: str) -> str:
    action_zh = "注册" if purpose == "signup" else "登录"
    action_en = "sign up" if purpose == "signup" else "sign in"
    return (
        f"你的 MosaelCloud {action_zh}验证码是: {code}\n"
        f"10 分钟内有效,只能用一次。不是你在操作就忽略这封邮件。\n\n"
        f"Your MosaelCloud {action_en} code is: {code}\n"
        f"It expires in 10 minutes and works once. Ignore this email if it wasn't you.\n"
    )


class SmtpCodeSender:
    """真实的发信实现。配置来自 `CLOUD_SMTP_*`,见 `CloudConfig`。"""

    def __init__(self, config: CloudConfig) -> None:
        self.config = config

    def ensure_ready(self) -> None:
        if not self.config.smtp_configured:
            raise CloudError(503, "mail_not_configured")

    def send_code(self, *, email: str, purpose: str, code: str) -> None:
        config = self.config
        self.ensure_ready()

        message = EmailMessage()
        message["From"] = config.smtp_from
        message["To"] = email
        message["Subject"] = _subject(purpose)
        #: 很多收件方会把缺少 Date / Message-ID 的自动邮件直接判成垃圾邮件。
        message["Date"] = formatdate(localtime=True)
        message["Message-ID"] = make_msgid(domain=config.smtp_from.rpartition("@")[2] or None)
        message.set_content(_body(purpose, code))

        try:
            if config.smtp_tls == "ssl":
                client = smtplib.SMTP_SSL(
                    config.smtp_host, config.smtp_port, timeout=SMTP_TIMEOUT_SECONDS
                )
            else:
                client = smtplib.SMTP(
                    config.smtp_host, config.smtp_port, timeout=SMTP_TIMEOUT_SECONDS
                )
            with client:
                client.ehlo()
                if config.smtp_tls == "starttls":
                    client.starttls()
                    client.ehlo()
                if config.smtp_username:
                    client.login(config.smtp_username, config.smtp_password)
                client.send_message(message)
            logger.info("sent %s code to %s", purpose, mask_email(email))
        except (OSError, smtplib.SMTPException) as failure:
            # 只有脱敏后的收件人和异常类型 —— 验证码本身绝不进日志。
            logger.warning(
                "could not send %s code to %s (%s)",
                purpose,
                mask_email(email),
                type(failure).__name__,
            )
            raise CloudError(502, "email_send_failed") from failure
