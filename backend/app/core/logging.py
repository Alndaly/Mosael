"""进程级日志配置。

问题:Uvicorn 只给自己的 logger(uvicorn / uvicorn.access / uvicorn.error)挂 handler,
业务代码的 `app.*` logger 会冒泡到 **没有 handler 的 root**,于是所有 INFO/DEBUG 都被
丢弃——现有那几条 `logger.info` 从来没人看得到。

方案:给 `app` 命名空间挂一个 stderr handler(所有 `logging.getLogger(__name__)`
在 app 包下的都归它),级别由 MOSAEL_LOG_LEVEL 决定,`propagate=False` 避免与 root/uvicorn
重复打印。noisy 的第三方库压到 WARNING。
"""

from __future__ import annotations

import logging
import sys

from app.core.config import settings

_configured = False

#: 定时轮询的端点在这个仓库里有统一的形状:`/<域>/worker/<动作>`(claim / heartbeat /
#: claim-check),由 sidecar 按秒发。用**结构**而不是一张路径名单来认它们 —— 名单会在
#: 下一个 worker 端点加进来时悄悄失效,而命名约定不会。
_POLL_MARKER = "/worker/"


class AccessLogFilter(logging.Filter):
    """压掉"什么都没发生"的轮询访问日志。

    用户的终端里一屏全是这个:

        INFO: 127.0.0.1 - "POST /api/browser/worker/claim HTTP/1.1" 200 OK
        INFO: 127.0.0.1 - "POST /api/publish/worker/heartbeat HTTP/1.1" 200 OK

    sidecar 每秒问一次"有活吗"、"我还活着",成功时一个字都不值得说 —— 说了反而把真正
    要看的那几行(任务失败、子进程 stderr)冲走。

    只压**成功**的:heartbeat 返 500 恰恰是最该看见的一行。看不懂形状的记录一律放行 ——
    过滤器宁可少压一条,也不能吃掉一条不认识的日志。
    """

    def __init__(self, *, quiet: bool) -> None:
        super().__init__()
        self.quiet = quiet

    def filter(self, record: logging.LogRecord) -> bool:
        if not self.quiet:
            return True
        args = record.args
        # uvicorn.access 的形状:(client, method, path, http_version, status)
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        path, status = args[2], args[4]
        if not isinstance(path, str) or not isinstance(status, int):
            return True
        return not (_POLL_MARKER in path and status < 400)

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

    # 轮询请求不刷屏。MOSAEL_LOG_ACCESS=all 恢复全量 —— 排查 sidecar 本身时就要看它们。
    access = logging.getLogger("uvicorn.access")
    access.filters = [f for f in access.filters if not isinstance(f, AccessLogFilter)]
    access.addFilter(AccessLogFilter(quiet=settings.log_access.strip().lower() != "all"))
