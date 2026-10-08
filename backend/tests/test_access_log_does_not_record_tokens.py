"""访问日志里不留登录令牌(SEC-8)。

`<img>` / `<video>` 带不了请求头,媒体、头像、预览的地址用 `?token=` 带上登录令牌;uvicorn 的访问日志原样记下完整地址,
整串令牌就以明文躺在日志里 —— 远程部署的日志常被收集、外发、给支持看。现在地址里的凭据参数换成 `<redacted>`,
压不压轮询日志(MOSAEL_LOG_ACCESS)都一样。
"""

from __future__ import annotations

import logging

import pytest

from app.core.logging import AccessLogFilter, redact_credentials

TOKEN = "a" * 64


def _access_record(path: str, status: int = 200) -> logging.LogRecord:
    """uvicorn.access 发出来的那种记录:args 是 (client, method, path, http_version, status)。"""
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:50000", "GET", path, "1.1", status), None,
    )


@pytest.mark.parametrize("quiet", [True, False], ids=["默认", "LOG_ACCESS=all"])
def test_地址里的令牌换成占位_别的参数照旧(quiet: bool) -> None:
    record = _access_record(f"/api/assets/x/thumbnail?v=3&token={TOKEN}&size=s")

    assert AccessLogFilter(quiet=quiet).filter(record)

    line = record.getMessage()
    assert TOKEN not in line
    assert "token=<redacted>" in line and "v=3" in line and "size=s" in line


def test_几种写法都认() -> None:
    assert redact_credentials(f"/x?token={TOKEN}") == "/x?token=<redacted>"
    assert redact_credentials(f"/x?a=1&Access_Token={TOKEN}#frag") == "/x?a=1&Access_Token=<redacted>#frag"
    assert redact_credentials("/x?secret=s3&b=2") == "/x?secret=<redacted>&b=2"
    assert redact_credentials("/x?tokens=1&mytoken=2") == "/x?tokens=1&mytoken=2", "不是这几个参数名的不动"


def test_装好的访问日志真的过这道(caplog, monkeypatch) -> None:
    from app.core import logging as app_logging

    monkeypatch.setattr(app_logging, "_configured", False)
    app_logging.configure_logging()
    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logging.getLogger("uvicorn.access").info(
            '%s - "%s %s HTTP/%s" %d', "127.0.0.1:1", "GET", f"/api/auth/users/u/avatar?token={TOKEN}", "1.1", 200,
        )
    assert caplog.records and TOKEN not in caplog.text and "token=<redacted>" in caplog.text


def test_轮询照旧不刷屏() -> None:
    assert not AccessLogFilter(quiet=True).filter(_access_record("/api/publish/worker/heartbeat"))
    assert AccessLogFilter(quiet=True).filter(_access_record("/api/publish/worker/heartbeat", 500))
