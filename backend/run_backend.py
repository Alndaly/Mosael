"""Packaged backend entry point (PyInstaller target).

Runs the FastAPI app on 127.0.0.1 only (plan §20). Port comes from
MIBU_BACKEND_PORT (default 8800).
"""

from __future__ import annotations

import os

import uvicorn

from app.main import app


def main() -> None:
    port = int(os.environ.get("MIBU_BACKEND_PORT", "8800"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")


if __name__ == "__main__":
    main()
