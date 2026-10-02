"""平台层:Alembic 迁移与模型一致、日志不漏密钥、配置检查、腾讯云短信的请求形状、命令行。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect

from community.cli import main as cli_main
from community.cli import migrate
from community.config import Settings
from community.db import Base
from community.logs import JsonFormatter, RedactingFilter
from community.sms import TencentSender


def test_alembic_从空库升到最新_和模型一致(tmp_path: Path) -> None:
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    migrate(url)
    engine = create_engine(url)
    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
        assert set(Base.metadata.tables) <= tables
        diff = compare_metadata(MigrationContext.configure(connection), Base.metadata)
    assert diff == [], f"models.py 改了但没有对应的迁移:{diff}"
    migrate(url)  # 再跑一次什么都不做


def _record(message: str, *args, **fields) -> logging.LogRecord:
    record = logging.LogRecord("community.test", logging.INFO, __file__, 1, message, args, None)
    record.fields = fields
    return record


def test_日志里不出现令牌_验证码_密码() -> None:
    formatter = JsonFormatter()
    redactor = RedactingFilter()
    secrets = {
        "jwt": "eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.c2lnbmF0dXJlLXNpZ25hdHVyZQ",
        "code": "482913",
        "password": "hunter2hunter2",
        "refresh": "Zm9vYmFyYmF6cXV4cXV1eA",
    }
    record = _record(
        "login with Bearer %s code=%s refresh_token=%s",
        secrets["jwt"],
        secrets["code"],
        secrets["refresh"],
        password=secrets["password"],
        refresh_token=secrets["refresh"],
        user_id="u1",
    )
    redactor.filter(record)
    line = formatter.format(record)
    for value in secrets.values():
        assert value not in line
    assert json.loads(line)["user_id"] == "u1"


def test_生产配置缺什么说什么() -> None:
    problems = Settings(env="production", sms_sender="console", cookie_secure=False).problems()
    text = "\n".join(problems)
    for name in ("COMMUNITY_SECRET_KEY", "COMMUNITY_JWT_PRIVATE_KEY", "COMMUNITY_SMS_SENDER", "COMMUNITY_COOKIE_SECURE"):
        assert name in text
    assert Settings(env="development").problems() == []


def test_腾讯云短信请求按模板变量顺序填() -> None:
    settings = Settings(
        tencent_sms_sdk_app_id="1400000000",
        tencent_sms_sign_name="示例签名",
        tencent_sms_template_id="100001",
        tencent_sms_template_id_reset="100003",
        tencent_sms_template_params="code,minutes",
    )
    sender = TencentSender(settings)
    request = sender.build_request("+8613800000000", "123456", purpose="login", ttl_minutes=5)
    assert request.SmsSdkAppId == "1400000000" and request.SignName == "示例签名"
    assert request.TemplateId == "100001" and request.TemplateParamSet == ["123456", "5"]
    assert request.PhoneNumberSet == ["+8613800000000"]
    assert sender.build_request("+8613800000000", "1", purpose="reset", ttl_minutes=5).TemplateId == "100003"


def test_命令行_建管理员_导入官方条目_生成密钥(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    monkeypatch.setenv("COMMUNITY_DATABASE_URL", url)
    monkeypatch.setenv("COMMUNITY_STORAGE_DIR", str(tmp_path / "media"))
    monkeypatch.setenv("COMMUNITY_ENV", "test")
    monkeypatch.setenv("COMMUNITY_SECRET_KEY", "k" * 40)
    assert cli_main(["migrate"]) == 0
    monkeypatch.setattr("sys.stdin", __import__("io").StringIO("a strong password\n"))
    assert cli_main(["create-admin", "--handle", "boss", "--phone", "13800000099", "--password-stdin"]) == 0
    assert cli_main(["seed-official"]) == 0
    assert cli_main(["seed-official"]) == 0
    out = capsys.readouterr().out
    assert "@boss" in out and "新建 0 项,新版本 0 项" in out
    key = tmp_path / "jwt.pem"
    assert cli_main(["gen-jwt-key", "--out", str(key)]) == 0
    assert key.read_text().startswith("-----BEGIN PRIVATE KEY-----")
    assert (key.stat().st_mode & 0o777) == 0o600
    monkeypatch.setenv("COMMUNITY_JWT_PRIVATE_KEY_FILE", str(key))
    from community.tokens import KeyRing

    assert KeyRing.from_settings(Settings()).private_key is not None


def test_社区服务的遥测全部关着_不读环境变量自己挂导出器(ctx) -> None:
    """FastAPI 0.142 起自带 OpenTelemetry,默认会读 OTEL_* 环境变量自己挂导出器。社区服务不往外发遥测。"""
    from community.app import create_app

    config = create_app(context=ctx)._telemetry
    assert config["auto_configure"] is False
    assert not any(config[key] for key in ("tracing", "metrics", "logs"))
