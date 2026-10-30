"""邮件头:自动邮件缺 Date / Message-ID 容易被收件方判成垃圾邮件。"""

from __future__ import annotations

import smtplib

from cloud.config import CloudConfig
from cloud.mailer import SmtpCodeSender


class FakeSmtp:
    sent = []

    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def ehlo(self):
        pass

    def starttls(self):
        pass

    def login(self, username, password):
        pass

    def send_message(self, message):
        self.sent.append(message)


def test_code_email_has_date_and_message_id(tmp_path, monkeypatch):
    fake = FakeSmtp()
    FakeSmtp.sent = []
    monkeypatch.setattr(smtplib, "SMTP_SSL", lambda *args, **kwargs: fake)
    config = CloudConfig(
        data_dir=tmp_path,
        public_url="https://mosael.test",
        cookie_secure=False,
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_tls="ssl",
        smtp_from="no-reply@example.com",
    )
    SmtpCodeSender(config).send_code(email="alice@example.com", purpose="login", code="123456")
    message = FakeSmtp.sent[0]
    assert message["Date"]
    assert message["Message-ID"].endswith("@example.com>")
