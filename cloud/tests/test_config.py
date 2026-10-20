"""配置:官方账号的三个 `CLOUD_OFFICIAL_*`,以及"短密码启动即失败"那道闸。

配置是启动路径:`cloud.main` / `cloud.cli` 都从 `CloudConfig.from_env()` 建一份。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from cloud.config import CloudConfig

CLOUD_ROOT = Path(__file__).resolve().parents[1]
SRC = CLOUD_ROOT / "src"


def _clear_cloud_env(monkeypatch, tmp_path: Path) -> None:
    for key in list(os.environ):
        if key.startswith("CLOUD_"):
            monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CLOUD_DATA_DIR", str(tmp_path))


def test_official_defaults_are_unset_password_and_mosael_identity(monkeypatch, tmp_path):
    """② 不设三个变量:默认 handle / email,**没有密码**(不报错)。"""
    _clear_cloud_env(monkeypatch, tmp_path)

    config = CloudConfig.from_env()
    assert config.official_handle == "mosael"
    assert config.official_email == "official@mosael.example"
    assert config.official_password == ""


def test_official_environment_variables_are_read_verbatim(monkeypatch, tmp_path):
    """② 三个变量都能覆盖默认值;密码原样保留(不 strip、不改写)。"""
    _clear_cloud_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CLOUD_OFFICIAL_HANDLE", "official-cat")
    monkeypatch.setenv("CLOUD_OFFICIAL_EMAIL", "ops@example.com")
    monkeypatch.setenv("CLOUD_OFFICIAL_PASSWORD", "Official-Horse-9")

    config = CloudConfig.from_env()
    assert config.official_handle == "official-cat"
    assert config.official_email == "ops@example.com"
    assert config.official_password == "Official-Horse-9"


def test_official_password_shorter_than_the_minimum_fails_config(monkeypatch, tmp_path):
    """④ 短密码**不静默**:配置构造就抛错(uvicorn 启动会因此退出)。"""
    _clear_cloud_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CLOUD_OFFICIAL_PASSWORD", "short")

    with pytest.raises(ValueError, match="CLOUD_OFFICIAL_PASSWORD"):
        CloudConfig.from_env()


def test_official_password_at_the_minimum_length_is_accepted(monkeypatch, tmp_path):
    """④ 边界:正好等于 CLOUD_PASSWORD_MIN_LENGTH 是合法的。"""
    _clear_cloud_env(monkeypatch, tmp_path)
    monkeypatch.setenv("CLOUD_PASSWORD_MIN_LENGTH", "8")
    monkeypatch.setenv("CLOUD_OFFICIAL_PASSWORD", "12345678")

    assert CloudConfig.from_env().official_password == "12345678"


def test_short_official_password_exits_the_server_entrypoint(tmp_path):
    """④ 真实的启动入口(`import cloud.main`)以非零退出码失败,stderr 说清是哪个变量。"""
    env = {key: value for key, value in os.environ.items() if not key.startswith("CLOUD_")}
    env.update(
        {
            "CLOUD_DATA_DIR": str(tmp_path),
            "CLOUD_OFFICIAL_PASSWORD": "short",
            "PYTHONPATH": str(SRC),
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", "import cloud.main"],
        cwd=CLOUD_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "CLOUD_OFFICIAL_PASSWORD" in result.stderr


def test_allowed_origins_can_list_several(monkeypatch):
    """本地开发时官网(3100)和桌面后端(8000)都要调接口 —— 它们是两个 Origin。

    没配就是 `public_url` 那一个(生产如此:官网和云同一个域名),**不是"什么来源都收"**。
    """
    from cloud.config import CloudConfig

    monkeypatch.setenv("CLOUD_PUBLIC_URL", "http://127.0.0.1:3100")
    monkeypatch.delenv("CLOUD_ALLOWED_ORIGINS", raising=False)
    one = CloudConfig.from_env()
    assert one.allowed_origins == frozenset({"http://127.0.0.1:3100"})

    monkeypatch.setenv("CLOUD_ALLOWED_ORIGINS", "http://127.0.0.1:3100, http://127.0.0.1:8000 ,")
    several = CloudConfig.from_env()
    assert several.allowed_origins == frozenset({"http://127.0.0.1:3100", "http://127.0.0.1:8000"})
