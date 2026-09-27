"""结构化日志。**日志里永远不出现验证码、令牌、密码。**

两道防线:

1. 写日志的地方只记「是哪一种事」和不敏感的字段(用户 id、会话 id、路径 —— **不带查询串**,上传地址的签名
   就在查询串里);请求体一律不记。
2. `RedactingFilter` 在出口再扫一遍:键名像密钥的字段整个换成 `[redacted]`,正文里形如
   `token=…`、`Bearer …`、JWT、6 位验证码跟在 code 后面的片段抹掉。第一道漏了,第二道兜住。

唯一的例外是开发用的 console 短信发送器 —— 它的职责就是把验证码打出来给开发者看,生产环境不允许用它
(见 config.Settings.problems)。
"""

from __future__ import annotations

import json
import logging
import re
import sys
from datetime import UTC, datetime
from typing import Any

SENSITIVE_KEYS = re.compile(r"(pass(word)?|secret|token|code|authorization|cookie|captcha|ticket|randstr|key)", re.I)

_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"),
    re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"(?i)(\b(?:refresh_token|access_token|device_code|password|secret|token|code|t)\s*[=:]\s*\"?)[^\s\"&,;]+"),
)

#: console 短信发送器的 logger 名。只有它允许带验证码(开发用)。
DEV_SMS_LOGGER = "community.sms.console"


def scrub(text: str) -> str:
    for pattern in _PATTERNS:
        text = pattern.sub(lambda m: (m.group(1) if m.groups() else "") + "[redacted]", text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == DEV_SMS_LOGGER:
            return True
        if record.args:
            try:
                record.msg = record.getMessage()
            except (TypeError, ValueError):
                record.msg = str(record.msg)
            record.args = None
        record.msg = scrub(str(record.msg))
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            record.fields = {
                key: "[redacted]" if SENSITIVE_KEYS.search(str(key)) else (scrub(value) if isinstance(value, str) else value)
                for key, value in fields.items()
            }
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
        }
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict):
            payload.update(fields)
        if record.exc_info:
            payload["exc"] = scrub(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        fields = getattr(record, "fields", None)
        if isinstance(fields, dict) and fields:
            base += " " + " ".join(f"{key}={value}" for key, value in fields.items())
        return base


class StdoutHandler(logging.StreamHandler):
    """写到**此刻的** sys.stdout(而不是配置那一刻的):测试框架、进程管理器换掉 stdout 之后照样写得进去。"""

    @property
    def stream(self):  # type: ignore[override]
        return sys.stdout

    @stream.setter
    def stream(self, _value) -> None:
        pass


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    handler = StdoutHandler()
    handler.setFormatter(JsonFormatter() if fmt == "json" else TextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(RedactingFilter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    # uvicorn 自己的访问日志带查询串(本地上传地址的签名就在里面):关掉,由 middleware 记不带查询串的那一行。
    logging.getLogger("uvicorn.access").disabled = True


def log_event(logger: logging.Logger, message: str, level: int = logging.INFO, **fields: Any) -> None:
    logger.log(level, message, extra={"fields": fields})


__all__ = ["DEV_SMS_LOGGER", "RedactingFilter", "configure_logging", "log_event", "scrub"]
