"""常驻的识别 worker:权重加载一次,不是每次识别加载一次。

进程管理住在 `worker_pool`(合成走同一套,那套东西的每一条都是撞出来的)。这里只绑定识别
这一侧不同的两样:事件怎么解码,以及报错时管这件事叫什么。

**为什么识别也要常驻。** 一次性模式下每次识别都重新读一遍模型 —— 一段十秒的音频里绝大部分
时间花在加载上,而上一次识别刚把同一个模型读进内存、进程一退就全扔了。批量转写场景下这笔
账不显眼(一小时的视频,加载那几十秒占比很小);**语音对话里它就是全部** —— 用户说完一句话
到看见回应,中间不能插一次模型加载。

超时比合成短得多:合成首次要读 18 GB 权重(实测 511.9 秒),识别的模型小一到两个数量级,
而且**下载不走这条路**(预热仍是一次性进程,见 workers/asr.main)。所以这里的等待只覆盖
"加载 + 解码",定成五分钟已经很宽。
"""

from __future__ import annotations

import threading
from pathlib import Path

from app.ai.runtime import workers
from app.ai.runtime.worker_pool import DEFAULT_IDLE_SECONDS, WorkerPool as _Pool
from app.ai.runtime.workers.asr_protocol import decode_event_line

WORKER_PATH = workers.asr_script()

#: 一次识别最长等多久。见模块说明:这里不含下载。
DEFAULT_TIMEOUT_SECONDS = 300


class WorkerPool(_Pool):
    """识别的常驻进程池。"""

    def __init__(
        self,
        *,
        worker_path: str | Path = WORKER_PATH,
        idle_seconds: float = DEFAULT_IDLE_SECONDS,
    ) -> None:
        super().__init__(
            worker_path=worker_path,
            decode=decode_event_line,
            noun="识别",
            idle_seconds=idle_seconds,
        )


#: 进程级的那一个。识别本来就被任务总线的 ASR 名额串行化(kind=transcribe 的准入槽是 1),
#: 不需要每个调用方各建一个池。
_POOL: WorkerPool | None = None
_POOL_LOCK = threading.Lock()


def pool() -> WorkerPool:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = WorkerPool()
        return _POOL
