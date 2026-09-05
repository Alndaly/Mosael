"""常驻的合成 worker:权重加载一次,不是每次合成加载一次。

实测这台机器上一次 Fish Speech 合成,**模型加载 511.9 秒**(18 GB 权重),而解码本身
2.37 it/s。用户看到的「20% 卡了 14 分钟」里,绝大部分时间花在重新读同一个模型上 ——
上一次合成刚把它读进内存,进程一退全扔了。

所以 worker 改成常驻:一个引擎一个进程,按行收发 JSON。第二次合成直接进推理。

**协议行带哨兵前缀**:引擎自己会往 stdout/stderr 打 tqdm 进度条和 loguru 日志,通道里
本来就有噪声。约定一个前缀、只认带前缀的行,比"假设子进程只说我们要的话"结实得多 ——
后者会在上游某次多打一行日志时安静地坏掉。

内存是**借**用户的:闲置超过 `idle_seconds` 就把进程放掉,而不是占到应用退出。
"""

from __future__ import annotations

import logging

import threading
from pathlib import Path

from app.ai.runtime import workers
from app.ai.runtime.workers.tts_protocol import decode_event_line
from app.ai.runtime.worker_pool import (
    DEFAULT_IDLE_SECONDS,
    ResidentWorker,
    WorkerPool as _Pool,
)

logger = logging.getLogger(__name__)

WORKER_PATH = workers.tts_script()



#: 进程管理住在 worker_pool(识别走同一套)。这里只绑定 TTS 这一侧不同的两样东西:
#: 事件怎么解码,以及报错时管这件事叫什么。
#:
#: `_Worker` 这个名字留着 —— 测试按它抓管道锁那条不变量(tests/test_downloads_can_run_in_parallel)。
_Worker = ResidentWorker


class WorkerPool(_Pool):
    """TTS 的常驻进程池。"""

    def __init__(
        self,
        *,
        worker_path: str | Path = WORKER_PATH,
        idle_seconds: float = DEFAULT_IDLE_SECONDS,
    ) -> None:
        super().__init__(
            worker_path=worker_path,
            decode=decode_event_line,
            noun="合成",
            idle_seconds=idle_seconds,
        )


#: 进程级的那一个。合成本来就被 TTS_SLOTS 串行化,不需要每个调用方各建一个池。
_POOL: WorkerPool | None = None
_POOL_LOCK = threading.Lock()


def pool() -> WorkerPool:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = WorkerPool()
        return _POOL
