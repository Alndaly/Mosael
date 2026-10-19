"""`uvicorn cloud.main:app` 的入口。配置从 `CLOUD_*` 环境变量读。"""

from __future__ import annotations

from cloud.app import create_app

app = create_app()
