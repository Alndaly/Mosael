"""「这件活不要了」:任务被取消时,把它手上**正在进行**的出站请求和子进程真的掐掉。

## 为什么要有

取消此前只落库:任务行改成已取消,工作流在节点边界停下 —— 而正在跑的那个节点里,一次大模型请求照样
等到答完。实测:取消之后本地 Ollama 一直生成到后端重启才停;付费 API 会一直计费到它自己答完。

## 怎么做

每个在进程内跑的任务有一个 `AbortScope`(jobs.dispatch_job 建、登记成任务的「子进程」—— 它有 `.kill()`,
取消级联到它时就调到它)。它放在上下文变量里,随工作流节点的线程池(copy_context)一路带下去。

- **出站 HTTP**:在作用域里建的 `RetryingClient`(core/http_retry,AI 出站调用都经过它)记下自己建的每一条连接的
  socket(httpx 的 trace 扩展,公开 API);取消时对它们 `shutdown(SHUT_RDWR)` —— 连接当场关掉、上游看到断开,
  阻塞在读上的那个线程立刻醒来。光 `close()` 不够:Linux 上关一个别的线程正在 recv 的 fd 不会叫醒它,连接也不会断。
  取消之后不再发新的请求、不再重试。
- **子进程**:任何一次性子进程(例如订阅授权那条路每次起一个 sidecar)登记一个 kill。

住在 core:它只认识 httpx 和 socket,没有任何领域概念;任务怎么建、怎么取消是 domain/jobs 的事。
"""

from __future__ import annotations

import contextvars
import itertools
import logging
import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import httpx

logger = logging.getLogger(__name__)


class RequestAborted(httpx.RequestError):
    """这次请求因为它所属的活被取消而中断(或者根本没发出去)。是 RequestError:调用方现有的「网络失败」分支照旧接得住,
    而重试层认得它、不再重试。"""


class AbortScope:
    """一件活的「不要了」开关。`kill()` 之后:登记过的回调各调一次,之后登记的当场调。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._hooks: dict[int, Callable[[], None]] = {}
        self._ids = itertools.count()

    @property
    def aborted(self) -> bool:
        return self._event.is_set()

    def kill(self) -> None:
        """取消(jobs.kill_job_child 调的就是它)。幂等。"""
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            hooks = list(self._hooks.values())
            self._hooks.clear()
        for hook in hooks:
            try:
                hook()
            except Exception:  # noqa: BLE001 — 一个回调失败不该拦住其余的
                logger.exception("取消回调失败")

    def on_abort(self, hook: Callable[[], None]) -> Callable[[], None]:
        """登记一个取消时要做的事,返回撤销登记的函数。已经取消了就当场做。"""
        with self._lock:
            if not self._event.is_set():
                key = next(self._ids)
                self._hooks[key] = hook
                return lambda: self._detach(key)
        hook()
        return lambda: None

    def _detach(self, key: int) -> None:
        with self._lock:
            self._hooks.pop(key, None)


_current: contextvars.ContextVar[AbortScope | None] = contextvars.ContextVar("mosael_abort_scope", default=None)


def current() -> AbortScope | None:
    """当前这件活的开关;不在任务里(请求线程、脚本)就是 None。"""
    return _current.get()


@contextmanager
def scope(one: AbortScope) -> Iterator[AbortScope]:
    token = _current.set(one)
    try:
        yield one
    finally:
        _current.reset(token)


class SocketReaper:
    """记下一个 httpx 客户端建的每一条连接,取消时把它们都关掉。

    用法:请求发出前 `request.extensions["trace"] = reaper.trace(request.extensions.get("trace"))`;客户端关闭时
    `reaper.close()`。连接是从 httpcore 的 trace 事件里拿到的(`connection.connect_tcp` / `connection.start_tls`
    完成时交回的那个流),所以连接池里复用的那几条也在 —— 它们是这个客户端自己建的。
    """

    def __init__(self, scope: AbortScope) -> None:
        self.scope = scope
        self._lock = threading.Lock()
        self._sockets: list[socket.socket] = []
        self._detach = scope.on_abort(self._shutdown_all)

    def trace(self, chained: Callable[[str, dict], None] | None) -> Callable[[str, dict], None]:
        def callback(event: str, info: dict) -> None:
            if event in ("connection.connect_tcp.complete", "connection.start_tls.complete"):
                stream = info.get("return_value")
                sock = stream.get_extra_info("socket") if stream is not None else None
                if isinstance(sock, socket.socket):
                    with self._lock:
                        self._sockets.append(sock)
                    if self.scope.aborted:  # 连上的那一刻已经被取消了
                        _shutdown(sock)
            if chained is not None:
                chained(event, info)

        return callback

    def _shutdown_all(self) -> None:
        with self._lock:
            sockets = list(self._sockets)
        for sock in sockets:
            _shutdown(sock)

    def close(self) -> None:
        self._detach()
        with self._lock:
            self._sockets.clear()


def _shutdown(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass  # 已经关了 / TLS 包装之后原来那个对象已经交出了 fd


__all__ = ["AbortScope", "RequestAborted", "SocketReaper", "current", "scope"]
