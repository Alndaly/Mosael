"""每个机器人一个长连接子进程(`python -m app.integrations.feishu.worker <bot_id>`)的起停。

独立进程是 lark_oapi SDK 的硬约束:它的 ws 客户端共享模块级事件循环,同一进程跑多条连接会互相污染。
"""

from __future__ import annotations

import logging
import os
import subprocess
import threading
from pathlib import Path

from sqlalchemy import select

from app.core import interpreter
from app.core.child_process import popen_text
from app.core.secrets_at_rest import child_handoff
from app.core.db import SessionLocal
from app.db.models import FeishuBot
from app.domain.feishu import bots

logger = logging.getLogger(__name__)

_processes: dict[str, subprocess.Popen] = {}
_process_lock = threading.Lock()


def start_connection(bot_id: str) -> None:
    backend_dir = Path(__file__).resolve().parents[3]
    python = backend_dir / ".venv" / "bin" / "python"
    with _process_lock:
        existing = _processes.get(bot_id)
        if existing is not None and existing.poll() is None:
            return
        bots.write_status(bot_id, "connecting")
        #: 子进程要解开机器人的 app_secret:主密钥按主进程拿到它的同一条路交下去(见 core/secrets_at_rest)。
        extra_env, key_line = child_handoff()
        process = popen_text(
            [str(python) if python.exists() else interpreter.base_python(), "-m", "app.integrations.feishu.worker", bot_id],
            cwd=backend_dir,
            env={**os.environ, **extra_env},
            stdin=subprocess.PIPE if key_line else None,
        )
        if key_line and process.stdin is not None:
            process.stdin.write(key_line)
            process.stdin.close()
        _processes[bot_id] = process


def stop_connection(bot_id: str) -> None:
    with _process_lock:
        process = _processes.pop(bot_id, None)
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    bots.write_status(bot_id, "offline")


def autostart_enabled_bots() -> None:
    with SessionLocal() as db:
        bots = db.scalars(select(FeishuBot).where(FeishuBot.enabled.is_(True))).all()
        for bot in bots:
            bot.status = "offline"
        db.commit()
        bot_ids = [bot.id for bot in bots]
    for bot_id in bot_ids:
        try:
            start_connection(bot_id)
        except Exception:
            logger.exception("feishu autostart failed bot=%s", bot_id)


def stop_all_connections() -> None:
    with _process_lock:
        ids = list(_processes)
    for bot_id in ids:
        stop_connection(bot_id)


def start_or_report(bot_id: str) -> None:
    """起连接;起不来就把原因写进机器人状态,而不是让建机器人的那个请求失败 —— 机器人已经存好了。"""
    try:
        start_connection(bot_id)
    except Exception:  # noqa: BLE001 —— 见上
        logger.exception("feishu connection failed to start bot=%s", bot_id)
        bots.write_status(bot_id, "error", "启动长连接失败")


def restart_connection(bot_id: str) -> None:
    stop_connection(bot_id)
    start_connection(bot_id)
