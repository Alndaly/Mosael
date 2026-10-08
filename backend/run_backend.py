"""Packaged backend entry point (PyInstaller target).

Runs the FastAPI app on 127.0.0.1 only (plan §20). Port comes from
MOSAEL_BACKEND_PORT (default 8800).

Given a management command instead (`mosael-backend reset-password <用户名>`, see app/cli), it runs that
against the same data directory and exits — the packaged app has no Python to run `python -m app.cli` with.
"""

from __future__ import annotations

import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import uvicorn


def config(port: int) -> uvicorn.Config:
    """打包版后端的 uvicorn 配置。关机时最多等还没结束的请求 GRACEFUL_SHUTDOWN_SECONDS 秒(见 core/lifeline)——
    默认的无限等会让一条开着的流把 lifespan 的收尾整段挡住。"""
    import uvicorn

    from app.core.lifeline import GRACEFUL_SHUTDOWN_SECONDS
    from app.main import app

    return uvicorn.Config(
        app, host="127.0.0.1", port=port, log_level="info", timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS
    )


def main() -> None:
    from app import cli

    if len(sys.argv) > 1 and sys.argv[1] in cli.COMMANDS:
        raise SystemExit(cli.main(sys.argv[1:]))

    import uvicorn

    port = int(os.environ.get("MOSAEL_BACKEND_PORT", "8800"))
    uvicorn.Server(config(port)).run()


if __name__ == "__main__":
    main()
