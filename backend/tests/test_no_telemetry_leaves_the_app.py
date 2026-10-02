"""FastAPI 0.142 起自带 OpenTelemetry,默认会读 OTEL_* 环境变量自己挂导出器。Mosael 不往外发遥测。"""

from __future__ import annotations

from app.main import create_app


def test_后端的遥测全部关着_不读环境变量自己挂导出器() -> None:
    config = create_app()._telemetry
    assert config["auto_configure"] is False
    assert not any(config[key] for key in ("tracing", "metrics", "logs"))
