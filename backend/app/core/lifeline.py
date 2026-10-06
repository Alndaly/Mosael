"""后端和拉起它的壳同生共死,并且说得清自己是谁。

**跟着壳走。** 桌面版的后端由 Electron 拉起。壳被强杀(SIGKILL、崩溃、任务管理器结束)时不会执行
任何清理代码,后端就成了孤儿:继续占着 8800 端口、握着数据库。下次打开应用,壳看见端口上有个健康的
后端就复用了它 —— 可能是旧版本、可能指着另一个数据目录。所以壳把自己的 pid 交下来
(``MOSAEL_PARENT_PID``),这里隔一会儿看一眼,壳没了就按正常流程关掉自己(lifespan 的收尾照走)。

**说得清自己是谁。** ``/api/health`` 带上版本、实例 id 和数据目录指纹,壳据此判断端口上那个后端
能不能复用,而不是只看它回不回 ``ok``。
"""

from __future__ import annotations

import hashlib
import logging
import os
import signal
import threading
import time
import uuid
from collections.abc import Callable

from app.core.child_process import process_alive

logger = logging.getLogger(__name__)

PARENT_ENV = "MOSAEL_PARENT_PID"

#: 这个后端进程的身份。每次启动都换 —— 壳和界面据此分辨「还是那一个」还是「已经重启过」。
INSTANCE_ID = uuid.uuid4().hex

#: 发出退出信号之后,等正常收尾的上限;到点还没退就直接退。
FORCE_EXIT_AFTER = 15.0


def data_dir_id(data_dir: object) -> str:
    """数据目录的指纹:不把路径本身暴露在不需要登录的接口上,但壳算得出同一个值来比对。

    按**原样的字符串**算,不做 resolve —— 壳传进来的就是这个字符串,两边不必对齐各自的规范化规则。"""
    return hashlib.sha256(str(data_dir).encode("utf-8")).hexdigest()[:16]


def parent_alive(pid: int) -> bool:
    """壳还在不在。探活本身(Windows 上不能用 os.kill(pid, 0))住在 child_process —— 本机服务接回上一个后端起的进程时也要它。"""
    return process_alive(pid)


def _shut_down() -> None:
    logger.warning("the shell that started this backend is gone; shutting down")
    # 走 uvicorn 自己的信号处理:lifespan 的收尾(停飞书连接、调度线程……)照常执行。
    signal.raise_signal(signal.SIGTERM)
    time.sleep(FORCE_EXIT_AFTER)
    os._exit(0)


def watch_parent(
    pid: int,
    *,
    interval: float = 2.0,
    on_gone: Callable[[], None] = _shut_down,
    alive: Callable[[int], bool] = parent_alive,
) -> threading.Thread:
    def run() -> None:
        while True:
            time.sleep(interval)
            try:
                if not alive(pid):
                    on_gone()
                    return
            except Exception:  # noqa: BLE001 —— 看门狗自己死了,孤儿就回来了,而没人会发现
                logger.exception("parent watchdog check failed")

    thread = threading.Thread(target=run, daemon=True, name="parent-watchdog")
    thread.start()
    return thread


def watch_parent_from_env() -> threading.Thread | None:
    raw = os.environ.get(PARENT_ENV, "").strip()
    if not raw.isdigit():
        return None
    return watch_parent(int(raw))
