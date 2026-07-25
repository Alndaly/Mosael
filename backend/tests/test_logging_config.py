"""进程级日志配置:app 命名空间挂 handler、幂等、噪声库压级。"""

from __future__ import annotations

import logging

import pytest

from app.core import logging as applog


@pytest.fixture
def restore_app_logger():
    """configure_logging 会改全局 logging 状态;测完还原,避免污染其它用例。"""
    lg = logging.getLogger("app")
    saved_handlers = lg.handlers[:]
    saved_propagate = lg.propagate
    saved_level = lg.level
    yield lg
    lg.handlers[:] = saved_handlers
    lg.propagate = saved_propagate
    lg.setLevel(saved_level)


def test_configure_logging_idempotent_and_scoped(restore_app_logger, monkeypatch):
    monkeypatch.setattr(applog, "_configured", False)
    lg = restore_app_logger
    applog.configure_logging()
    assert len(lg.handlers) == 1
    assert lg.propagate is False  # 不冒泡到 root,避免与 uvicorn/lastResort 重复
    assert lg.level == logging.INFO
    applog.configure_logging()  # 第二次是 no-op
    assert len(lg.handlers) == 1


def test_configure_logging_respects_level(restore_app_logger, monkeypatch):
    monkeypatch.setattr(applog, "_configured", False)
    monkeypatch.setattr(applog.settings, "log_level", "DEBUG")
    applog.configure_logging()
    assert restore_app_logger.level == logging.DEBUG


def test_noisy_libraries_capped(restore_app_logger, monkeypatch):
    monkeypatch.setattr(applog, "_configured", False)
    applog.configure_logging()
    assert logging.getLogger("httpx").level == logging.WARNING


def test_app_child_logger_reaches_handler(restore_app_logger, monkeypatch, capsys):
    monkeypatch.setattr(applog, "_configured", False)
    applog.configure_logging()  # handler 绑定到当前(capsys 替换后的)stderr
    logging.getLogger("app.test.trace").info("hello-trace-line")
    assert "hello-trace-line" in capsys.readouterr().err
