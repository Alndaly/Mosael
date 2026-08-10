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

import json
import logging
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)

#: 协议行的前缀。子进程的其它输出一律当日志。
EVENT_PREFIX = "@@OPEN-STUDIO-TTS "

WORKER_PATH = Path(__file__).with_name("tts_worker.py")

#: 一次合成最长等多久(权重首次加载可能就要 8 分钟)。
DEFAULT_TIMEOUT_SECONDS = 1800
#: 闲多久放掉进程。默认十分钟:再点一次通常还在这个窗口里,而放着不用的 18 GB 该还回去。
DEFAULT_IDLE_SECONDS = 600


class _Worker:
    """一个常驻子进程。**同一时刻只服务一个请求** —— 外面有 TTS_SLOTS 串行化。"""

    def __init__(self, engine: str, python: str, worker_path: str, env: dict[str, str] | None) -> None:
        self.engine = engine
        self.python = python
        self.started_at = time.monotonic()
        self.last_used = time.monotonic()
        self.process = subprocess.Popen(
            [python, worker_path, "--serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        # stderr 必须有人一直读:不读满一个管道缓冲区,子进程就会卡在 write 上永远不返回
        # (见 core/child_process 那段"四个地方各犯一次"的记录)。这里只把它当日志。
        threading.Thread(target=self._drain_stderr, daemon=True).start()

    def _drain_stderr(self) -> None:
        assert self.process.stderr is not None
        for line in self.process.stderr:
            text = line.rstrip()
            if text:
                logger.debug("[%s worker] %s", self.engine, text[:400])

    @property
    def alive(self) -> bool:
        return self.process.poll() is None

    def request(
        self,
        payload: dict,
        *,
        on_progress: Callable[[dict], None] | None,
        timeout: float,
    ) -> dict:
        assert self.process.stdin is not None and self.process.stdout is not None
        self.last_used = time.monotonic()
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

        deadline = time.monotonic() + timeout
        for line in self.process.stdout:
            if not line.startswith(EVENT_PREFIX):
                text = line.rstrip()
                if text:
                    logger.debug("[%s worker] %s", self.engine, text[:400])
                continue
            event = json.loads(line[len(EVENT_PREFIX):])
            kind = event.get("event")
            if kind == "progress":
                if on_progress:
                    on_progress(event)
                continue
            if kind == "error":
                raise RuntimeError(event.get("message") or "合成失败")
            if kind == "done":
                self.last_used = time.monotonic()
                return event
            logger.debug("未知事件:%s", event)
            if time.monotonic() > deadline:
                break
        # 走到这里 = stdout 关了(进程死了)或超时。**最坏的失败是没有回音** ——
        # 那看起来和"还在跑"一模一样,所以必须变成一个明确的错误。
        self.kill()
        raise RuntimeError("合成进程中途退出,没有给出结果")

    def kill(self) -> None:
        try:
            self.process.kill()
        except OSError:
            pass


class WorkerPool:
    """按 (引擎, 解释器) 维护常驻进程。"""

    def __init__(
        self,
        *,
        worker_path: str | Path = WORKER_PATH,
        idle_seconds: float = DEFAULT_IDLE_SECONDS,
    ) -> None:
        self._worker_path = str(worker_path)
        self._idle_seconds = idle_seconds
        self._workers: dict[tuple[str, str], _Worker] = {}
        self._lock = threading.Lock()
        self._reaper = threading.Thread(target=self._reap_idle, daemon=True)
        self._stop = threading.Event()
        self._reaper.start()

    def request(
        self,
        engine: str,
        python: str,
        payload: dict,
        *,
        on_progress: Callable[[dict], None] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        env: dict[str, str] | None = None,
    ) -> dict:
        worker = self._ensure(engine, python, env)
        try:
            return worker.request(payload, on_progress=on_progress, timeout=timeout)
        except RuntimeError:
            # 死掉的进程不留在池子里 —— 下一次请求该拿到一个新的,而不是同一个尸体。
            with self._lock:
                if self._workers.get((engine, python)) is worker:
                    self._workers.pop((engine, python), None)
            worker.kill()
            raise

    def alive(self, engine: str, python: str) -> bool:
        with self._lock:
            worker = self._workers.get((engine, python))
        return bool(worker and worker.alive)

    def kill(self, engine: str, python: str) -> None:
        with self._lock:
            worker = self._workers.pop((engine, python), None)
        if worker:
            worker.kill()

    def drop_all(self) -> str:
        """放掉现有进程,**池子继续可用**。配置改了走这条:下一次合成起一个带新 env 的。"""
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.kill()
        return f"放掉了 {len(workers)} 个常驻合成进程"

    def shutdown(self) -> None:
        """进程要退出了。**回收线程也停掉** —— 之后这个池子不该再被用。"""
        self._stop.set()
        self.drop_all()

    def _ensure(self, engine: str, python: str, env: dict[str, str] | None = None) -> _Worker:
        with self._lock:
            worker = self._workers.get((engine, python))
            if worker and worker.alive:
                return worker
            if worker:
                logger.info("%s 的合成进程已经不在了,重新起一个", engine)
            # env 在**起进程时**定下:fish 靠 OPEN_STUDIO_FISH_* 找检出和权重。配置改了之后
            # 常驻进程会抱着旧 env 不放,所以设置页保存时调 shutdown() 让它重起(见 routes/voices)。
            worker = _Worker(engine, python, self._worker_path, env)
            self._workers[(engine, python)] = worker
            return worker

    def _reap_idle(self) -> None:
        while not self._stop.wait(1.0):
            cutoff = time.monotonic() - self._idle_seconds
            with self._lock:
                stale = [key for key, w in self._workers.items() if w.last_used < cutoff]
                dropped = [self._workers.pop(key) for key in stale]
            for worker in dropped:
                logger.info("%s 的合成进程闲置超时,放掉(把内存还回去)", worker.engine)
                worker.kill()


#: 进程级的那一个。合成本来就被 TTS_SLOTS 串行化,不需要每个调用方各建一个池。
_POOL: WorkerPool | None = None
_POOL_LOCK = threading.Lock()


def pool() -> WorkerPool:
    global _POOL
    with _POOL_LOCK:
        if _POOL is None:
            _POOL = WorkerPool()
        return _POOL
