"""进程级日志配置。

问题:Uvicorn 只给自己的 logger(uvicorn / uvicorn.access / uvicorn.error)挂 handler,
业务代码的 `app.*` logger 会冒泡到 **没有 handler 的 root**,于是所有 INFO/DEBUG 都被
丢弃——现有那几条 `logger.info` 从来没人看得到。

方案:给 `app` 命名空间挂一个 stderr handler(所有 `logging.getLogger(__name__)`
在 app 包下的都归它),级别由 MIBU_LOG_LEVEL 决定,`propagate=False` 避免与 root/uvicorn
重复打印。noisy 的第三方库压到 WARNING。
"""

from __future__ import annotations

import logging
import sys

from app.core.config import settings

_configured = False

# 每请求一行 INFO 的库,压到 WARNING 免得淹没业务日志。
_NOISY_LIBRARIES = ("httpx", "httpcore", "urllib3", "openai", "PIL")


def configure_logging() -> None:
    """给 app 命名空间配置好日志输出。幂等:重复调用不会叠加 handler。"""
    global _configured
    if _configured:
        return
    _configured = True

    level = getattr(logging, settings.log_level.strip().upper(), logging.INFO)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    app_logger = logging.getLogger("app")
    app_logger.handlers.clear()
    app_logger.addHandler(handler)
    app_logger.setLevel(level)
    app_logger.propagate = False  # 不再冒泡到 root,避免和 uvicorn 的 handler 重复

    for noisy in _NOISY_LIBRARIES:
        logging.getLogger(noisy).setLevel(logging.WARNING)
