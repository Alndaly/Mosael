"""常驻 worker 进程池:权重加载一次,不是每次请求加载一次。

这里**不认识任何一种 worker** —— 它只管「起一个按行收发 JSON 的子进程、别让它串、别让它
卡死、闲了把内存还回去」。合成和识别各自的事件形状由绑定层给(`decode`),报错时怎么称呼
这件事也由绑定层给(`noun`)。

抽出来是因为识别要走同一条路。这套东西的每一条都是撞出来的 —— 管道锁、stderr 排空、
看门狗、"回收的判据是闲着而不是时间戳"—— 抄第二份的话,修好的只会是其中一份。
"""

from __future__ import annotations

import json
import logging
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from app.core.child_process import popen_text

logger = logging.getLogger(__name__)

#: 一行 → 事件,认不出就 None(那是子进程自己的日志/进度条,不是给我们的)。
Decode = Callable[[str], dict | None]

#: 一次请求最长等多久(权重首次加载可能就要 8 分钟)。
DEFAULT_TIMEOUT_SECONDS = 1800
#: 闲多久放掉进程。默认十分钟:再点一次通常还在这个窗口里,而放着不用的十几 GB 该还回去。
DEFAULT_IDLE_SECONDS = 600


class ResidentWorker:
    """一个常驻子进程。**同一时刻只服务一个请求** —— 由它自己保证。

    此前这句话靠"外面有 TTS_SLOTS 串行化"兑现,而那个信号量只在合成那条路上
    (`domain/voices/voices`)。下 F5 多语言权重走的是同一个常驻进程,却**绕过了它** ——
    一边下语言包一边点配音,两个请求就一起写进同一个 stdin,两个线程一起读同一个 stdout,
    响应串到别人手里。一个不变量交给 N 个调用方各自记得,迟早有一个不记得。

    所以锁放在这里:谁来都排队,不用知道别人存不存在。
    """

    def __init__(
        self,
        engine: str,
        python: str,
        worker_path: str,
        env: dict[str, str] | None,
        *,
        decode: Decode,
        noun: str,
    ) -> None:
        #: 怎么从一行里认出事件。**每种 worker 的 done 形状不同**(合成给的是文件路径,
        #: 识别给的是语言与分段),所以解码交给绑定层,进程管理这一层不认识任何一种。
        self._decode = decode
        #: 报错时怎么称呼这件事(「合成」/「识别」)。用户读到的是这个词。
        self._noun = noun
        #: 一次只让一个请求进 stdin/stdout。**不是** TTS_SLOTS 那种"限制并发合成数"的名额,
        #: 这条只保护这一个进程的管道不被两个请求同时用。
        self._pipe_lock = threading.Lock()
        self.engine = engine
        self.python = python
        self.started_at = time.monotonic()
        self.last_used = time.monotonic()
        #: 有请求在飞。**回收的判据是"闲着",不是"上次用完过了多久"** —— 首次加载权重要
        #: 511 秒,比闲置超时还长,只看时间戳会把一个正在干活的进程当成闲置的杀掉
        #: (真机第一次验证就死在这儿)。
        self.busy = False
        #: 是被看门狗杀的,还是自己死的。两者给用户的话不一样。
        self.timed_out = False
        self.process = popen_text(
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
        """把子进程的 stderr 一直读空。

        **这个线程死了就是死锁**:没人读,管道写满(约 64KB),子进程卡在 write 上永远不返回
        —— 正是 core/child_process 开头记的那个"同一个错误在四个地方各犯一次"。所以它必须
        扛得住一切:子进程写什么都可能(非法 UTF-8、二进制),而没人 join 它、没人会发现它没了。
        """
        assert self.process.stderr is not None
        try:
            for line in self.process.stderr:
                text = line.rstrip()
                if text:
                    logger.debug("[%s worker] %s", self.engine, text[:400])
        except Exception as exc:  # noqa: BLE001 — 排空比读懂重要
            logger.warning("%s 的 stderr 读不下去了(%s),继续排空以免子进程卡死", self.engine, exc)
            try:
                self.process.stderr.detach().read()  # 只丢弃,不解码
            except Exception:  # noqa: BLE001
                logger.debug("%s 的 stderr 已经关了", self.engine)

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
        with self._pipe_lock:
            return self._request_locked(payload, on_progress=on_progress, timeout=timeout)

    def _request_locked(
        self,
        payload: dict,
        *,
        on_progress: Callable[[dict], None] | None,
        timeout: float,
    ) -> dict:
        self.busy = True
        self.last_used = time.monotonic()
        self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self.process.stdin.flush()

        # **超时靠杀进程兑现,不靠循环里检查。** `for line in stdout` 阻塞在 readline 上:
        # worker 活着却不说话时(卡在一次下载、卡在 torch 的某个锁上),这个循环永远不返回,
        # 于是任务永远不失败、busy 永远为真、TTS_SLOTS 的名额被一直占着 —— 之后所有配音
        # 永久排队。看门狗到点就 kill,readline 随即读到 EOF,走下面那条明确的错误路径。
        watchdog = threading.Timer(timeout, self._kill_for_timeout)
        watchdog.daemon = True
        watchdog.start()
        try:
            return self._read_until_done(on_progress)
        finally:
            watchdog.cancel()

    def _kill_for_timeout(self) -> None:
        logger.warning("%s 的%s进程没有回音,杀掉", self.engine, self._noun)
        self.timed_out = True
        self.kill()

    def _read_until_done(self, on_progress: Callable[[dict], None] | None) -> dict:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            event = self._decode(line)
            if event is None:
                text = line.rstrip()
                if text:
                    logger.debug("[%s worker] %s", self.engine, text[:400])
                continue
            kind = event.get("event")
            if kind == "progress":
                if on_progress:
                    on_progress(event)
                continue
            if kind == "error":
                self.busy = False
                raise RuntimeError(event.get("message") or f"{self._noun}失败")
            if kind == "done":
                self.last_used = time.monotonic()
                self.busy = False
                return event
            logger.debug("未知事件:%s", event)
        # 走到这里 = stdout 关了(进程死了)或超时。**最坏的失败是没有回音** ——
        # 那看起来和"还在跑"一模一样,所以必须变成一个明确的错误。
        self.busy = False
        self.kill()
        if self.timed_out:
            raise RuntimeError(f"{self._noun}超时,没有回音 —— 进程已被终止")
        raise RuntimeError(f"{self._noun}进程中途退出,没有给出结果")

    def kill(self) -> None:
        try:
            self.process.kill()
        except OSError:
            pass


class WorkerPool:
    """按 (引擎, 解释器) 维护常驻进程。**不认识任何一种 worker** —— 解码器与名词由绑定层给。"""

    def __init__(
        self,
        *,
        worker_path: str | Path,
        decode: Decode,
        noun: str,
        idle_seconds: float = DEFAULT_IDLE_SECONDS,
    ) -> None:
        self._worker_path = str(worker_path)
        self._decode = decode
        self._noun = noun
        self._idle_seconds = idle_seconds
        self._workers: dict[tuple[str, str], ResidentWorker] = {}
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
        """放掉现有进程,**池子继续可用**。配置改了走这条:下一次起一个带新 env 的。"""
        with self._lock:
            workers = list(self._workers.values())
            self._workers.clear()
        for worker in workers:
            worker.kill()
        return f"放掉了 {len(workers)} 个常驻{self._noun}进程"

    def shutdown(self) -> None:
        """进程要退出了。**回收线程也停掉** —— 之后这个池子不该再被用。"""
        self._stop.set()
        self.drop_all()

    def _ensure(self, engine: str, python: str, env: dict[str, str] | None = None) -> ResidentWorker:
        with self._lock:
            worker = self._workers.get((engine, python))
            if worker and worker.alive:
                return worker
            if worker:
                logger.info("%s 的%s进程已经不在了,重新起一个", engine, self._noun)
            # env 在**起进程时**定下:fish 靠 MOSAEL_FISH_* 找检出和权重。配置改了之后
            # 常驻进程会抱着旧 env 不放,所以设置页保存时调 shutdown() 让它重起(见 routes/voices)。
            worker = ResidentWorker(engine, python, self._worker_path, env, decode=self._decode, noun=self._noun)
            self._workers[(engine, python)] = worker
            return worker

    def _reap_idle(self) -> None:
        """闲置回收。**一次意外不能让它死掉** —— 它一死,闲置的十几 GB 就再也回不来,
        而没有任何东西会变红:没人 join 它,traceback 打到 stderr 就完了。"""
        while not self._stop.wait(1.0):
            try:
                self._reap_once()
            except Exception:  # noqa: BLE001 — 这一轮出错就跳过这一轮,别把线程赔进去
                logger.exception("闲置回收这一轮出错,跳过")

    def _reap_once(self) -> None:
        cutoff = time.monotonic() - self._idle_seconds
        with self._lock:
            stale = [key for key, w in self._workers.items()
                     if not getattr(w, "busy", False) and getattr(w, "last_used", 0.0) < cutoff]
            dropped = [self._workers.pop(key) for key in stale]
        for worker in dropped:
            logger.info("%s 的%s进程闲置超时,放掉(把内存还回去)", getattr(worker, "engine", "?"), self._noun)
            worker.kill()
