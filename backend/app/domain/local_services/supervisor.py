"""本机服务的进程:起、看健康、崩了退避重启、停,以及「同一个目录只起一份」(ADR 0041 §2)。

**这里不认识数据库,也不认识插件。** 怎么起(命令行、环境、健康检查的路径)由调用方算好交进来(`LaunchSpec`),
崩了要重起时也问调用方要一份新的(`respawn`)—— 那一步要读库、要问插件,归 `local_services` 的领域那一层。
这样测试能拿一个几行的假服务把这里的每条路都走一遍,不用起插件。

状态(界面按 1200 ms 轮询):

    stopped ──start──▶ starting ──健康检查通过──▶ running ──意外退出──▶ restarting ──就绪──▶ running
                          │                                                    │
                          └── 没在限时内就绪 / 起来前就退出 ──▶ failed ◀── 5 分钟内第 4 次 ──┘

- **起**:`own_group` 自成一组,stdout / stderr 直接写日志文件(见 logs);
- **就绪**:每 HEALTH_POLL_SECONDS 问一次健康检查,直到插件给的上限(第一次启动要解包前端、加载自定义节点);
- **崩溃**:运行中意外退出 → 自动重启,1 秒起翻倍,5 分钟内最多 3 次(和 Electron 管后端同一条规矩);再崩就停在
  「起不来」,把最后 40 行日志摆出来。第一次就没起来的(参数不对、缺依赖、端口被占)不重试:那几乎总是每次都一样;
- **停**:先请整组自己退(SIGTERM / CTRL_BREAK),STOP_GRACE_SECONDS 后强杀整组。
"""

from __future__ import annotations

import http.client
import logging
import os
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from urllib import request

from app.core.child_process import kill_group, kill_tree, process_alive, spawn_to_file, terminate_group
from app.core.i18n import LocalizedError
from app.domain.local_services import pidfiles
from app.domain.local_services.errors import LocalServiceError
from app.domain.local_services.logs import ServiceLog

logger = logging.getLogger(__name__)

STOPPED = "stopped"
STARTING = "starting"
RUNNING = "running"
RESTARTING = "restarting"
FAILED = "failed"
STATES = (STOPPED, STARTING, RUNNING, RESTARTING, FAILED)
#: 进程在(或马上要在)的那几种:这时候它占着目录和端口。
ACTIVE = frozenset({STARTING, RUNNING, RESTARTING})

#: 多久问一次健康检查(ADR 0041 §2)。
HEALTH_POLL_SECONDS = 0.5
#: 一次健康检查最多等多久。它在本机,不该慢。
HEALTH_TIMEOUT_SECONDS = 2.0
#: 插件没说时,第一次启动最多等多久就绪。
DEFAULT_READY_TIMEOUT = 180.0
#: 运行中多久看一眼它还在不在(顺带把新日志读进缓冲)。
WATCH_SECONDS = 1.0
#: 停:请它自己退之后等多久再强杀整组。
STOP_GRACE_SECONDS = 10.0
#: 崩溃重启:RESTART_WINDOW_SECONDS 里最多 MAX_RESTARTS 次,RESTART_BASE_DELAY 起翻倍。
MAX_RESTARTS = 3
RESTART_WINDOW_SECONDS = 300.0
RESTART_BASE_DELAY = 1.0
#: 起不来时摆出来的日志行数。
FAILURE_TAIL_LINES = 40

#: 健康检查不走任何代理:它问的是本机。
_OPENER = request.build_opener(request.ProxyHandler({}))


@dataclass(frozen=True)
class LaunchSpec:
    """起一次要的全部东西(插件的 `service_launch` 加上宿主那一半环境,见 local_services)。"""

    argv: list[str]
    env: dict[str, str]
    cwd: str
    port: int
    health_path: str
    ready_timeout: float = DEFAULT_READY_TIMEOUT
    #: 用户选的目录(记进 pid 文件,给人看)。
    directory: str = ""

    @property
    def health_url(self) -> str:
        return f"http://127.0.0.1:{self.port}{self.health_path}"


#: 崩了要重起时,问调用方要一份新的起法(配置可能改过;接回来的进程本来就没有)。
Respawn = Callable[[], LaunchSpec]


def healthy(url: str) -> bool:
    """健康检查:那条路径回 2xx。连不上、超时、回别的都不算。"""
    try:
        with _OPENER.open(url, timeout=HEALTH_TIMEOUT_SECONDS) as response:
            return 200 <= response.status < 300
    except (OSError, ValueError, http.client.HTTPException):
        return False


def port_in_use(port: int) -> bool:
    """这个端口现在有没有人在听(本机回环或全部地址上)。

    POSIX 上试绑时带 SO_REUSEADDR:刚停掉的服务端口上还挂着 TIME_WAIT 的连接(健康检查问过的那几次),不带它试绑会失败
    一两分钟 —— 「重启」就成了「端口被占」。服务自己(ComfyUI、aiohttp)也是带着它绑的,所以这样问和它起得来是同一个答案;
    真有人在听,带着它也绑不上。Windows 上这个选项的意思是「抢过来」,不带。
    """
    for host in ("127.0.0.1", "0.0.0.0"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if sys.platform != "win32":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
            except OSError:
                return True
    return False


class RestartPolicy:
    """5 分钟内最多 3 次、1 秒起翻倍(和 electron/backend-lifecycle.cjs 的 createRestartPolicy 同一条)。"""

    def __init__(self) -> None:
        self._recent: deque[float] = deque()

    def _prune(self, now: float) -> None:
        while self._recent and now - self._recent[0] > RESTART_WINDOW_SECONDS:
            self._recent.popleft()

    def next_delay(self, now: float) -> float | None:
        """这一次崩溃之后等多久再起;None = 窗口里已经重启够次数了,不再起。"""
        self._prune(now)
        if len(self._recent) >= MAX_RESTARTS:
            return None
        delay = RESTART_BASE_DELAY * 2 ** len(self._recent)
        self._recent.append(now)
        return delay

    def recent(self, now: float) -> int:
        self._prune(now)
        return len(self._recent)


class _Handle:
    """一个在跑的进程:我们起的(有 Popen)或接回来的(只有 pid —— 它不是我们的子进程,等不了它退出,只能隔一会儿看一眼)。"""

    def __init__(self, pid: int, popen=None) -> None:
        self.pid = pid
        self.popen = popen

    def alive(self) -> bool:
        if self.popen is not None:
            return self.popen.poll() is None
        if sys.platform != "win32":
            # 只有 pid 的那个碰巧是这个进程的子进程(同一个进程里先起后丢了句柄):退了就是僵尸,探活照样说「在」,得先收掉
            try:
                reaped, _status = os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                reaped = 0  # 不是我们的子进程(上一个后端起的):只能看它在不在
            if reaped == self.pid:
                return False
        return process_alive(self.pid)

    def wait(self, timeout: float) -> bool:
        """最多等 `timeout` 秒;退了回 True。"""
        if self.popen is not None:
            try:
                self.popen.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                return False
            return True
        deadline = time.monotonic() + timeout
        while self.alive():
            if time.monotonic() >= deadline:
                return False
            time.sleep(min(0.2, timeout))
        return True

    def exit_code(self) -> int | None:
        return self.popen.poll() if self.popen is not None else None

    def terminate(self) -> None:
        terminate_group(self.pid)

    def kill(self) -> None:
        if self.popen is not None:
            kill_tree(self.popen)
        else:
            kill_group(self.pid)


class _Outcome(Enum):
    READY = "ready"
    EXITED = "exited"
    TIMEOUT = "timeout"
    STOPPING = "stopping"


class ServiceProcess:
    """一个连接的本机服务进程。一个连接一个,常驻在 `_services` 里;线程安全。"""

    def __init__(self, instance_id: str, log: ServiceLog) -> None:
        self.instance_id = instance_id
        self.log = log
        self._cond = threading.Condition()
        self.state = STOPPED
        #: 停在「起不来」时的原因(带文案 key,按看的人的语言说)和最后几行日志。
        self.error: LocalizedError | None = None
        self.failure_lines: list[str] = []
        self.pid: int | None = None
        self.port: int | None = None
        #: 这一次进程起来的时刻(给人看)。
        self.started_at: datetime | None = None
        #: 上一次从起到健康检查通过用了多久(冷启动的那一次也在这里)。
        self.ready_seconds: float | None = None
        #: 这个进程是上一个后端起的、这次接回来的。
        self.adopted = False
        self.directory_key = ""
        #: 健康检查通过时叫一声(在另一个线程里叫:它可能要问插件刷新目录,不能挡着看护)。
        self.on_ready: Callable[[], None] | None = None
        #: 这一次起法给的就绪上限(等它就绪的人据此决定等多久)。
        self.ready_timeout = DEFAULT_READY_TIMEOUT
        #: 「起」这件事一次只做一回:两次插件调用同时要用它时,第二个等第一个起完(否则它会看见端口被第一个占着)。
        self.start_lock = threading.Lock()
        self._handle: _Handle | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._policy = RestartPolicy()
        self._respawn: Respawn | None = None
        self._spawned_at = 0.0

    # ---- 对外 ----

    @property
    def active(self) -> bool:
        return self.state in ACTIVE

    def launch(self, spec: LaunchSpec, respawn: Respawn) -> None:
        """从头起。已经在跑(或正在起、正在重启)就什么都不做。起不来(找不到解释器)当场抛,状态停在「起不来」。"""
        with self._cond:
            if self.active:
                return
            self._stop = threading.Event()
            self._policy = RestartPolicy()
            self._respawn = respawn
            self.error, self.failure_lines, self.adopted, self.ready_seconds = None, [], False, None
            try:
                handle = self._spawn(spec, fresh=True)
            except OSError as exc:
                error = LocalServiceError("localServiceErr_spawnFailed", status=422, detail=str(exc))
                self._fail_locked(error)
                raise error from exc
            self._set_locked(STARTING)
            self._thread = threading.Thread(
                target=self._supervise, args=(handle, spec, False), daemon=True, name=f"local-service-{self.instance_id[:8]}"
            )
            self._thread.start()

    def adopt(self, record: pidfiles.PidRecord, respawn: Respawn) -> None:
        """把上一个后端起的那个接回来,当作运行中(调用方已经核对过它就是那一个,见 pidfiles)。"""
        with self._cond:
            if self.active:
                return
            self._stop = threading.Event()
            self._policy = RestartPolicy()
            self._respawn = respawn
            self.error, self.failure_lines, self.ready_seconds = None, [], None
            self._handle = _Handle(record.pid)
            self.pid, self.port, self.adopted = record.pid, record.port, True
            self.started_at = _parse_time(record.started_at)
            self.log.follow_existing()
            self._set_locked(RUNNING)
            spec = LaunchSpec(argv=record.argv, env={}, cwd=record.cwd, port=record.port, health_path=record.health_path,
                              directory=record.directory)
            self._thread = threading.Thread(
                target=self._supervise, args=(self._handle, spec, True), daemon=True,
                name=f"local-service-{self.instance_id[:8]}",
            )
            self._thread.start()

    def stop(self, grace: float | None = None) -> None:
        """停:先请整组自己退,`grace` 秒后(缺省 STOP_GRACE_SECONDS)强杀整组。没在跑就什么都不做。"""
        grace = STOP_GRACE_SECONDS if grace is None else grace
        with self._cond:
            self._stop.set()
            handle, thread = self._handle, self._thread
            if handle is None and not self.active:
                return
        if handle is not None and handle.alive():
            handle.terminate()
            if not handle.wait(grace):
                logger.warning("本机服务 %s 在 %.0f 秒内没自己退,强杀整组", self.instance_id, grace)
                handle.kill()
                handle.wait(5.0)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=grace + 5.0)
        with self._cond:
            if self._handle is handle or self.active:
                self._finish_locked(STOPPED)

    def wait_settled(self, timeout: float) -> str:
        """等到它不再是「启动中 / 重启中」(就绪了、起不来了、被停了),最多 `timeout` 秒。回那时的状态。"""
        with self._cond:
            self._cond.wait_for(lambda: self.state not in (STARTING, RESTARTING), timeout)
            return self.state

    def restarts(self) -> int:
        return self._policy.recent(time.monotonic())

    # ---- 看护 ----

    def _supervise(self, handle: _Handle, spec: LaunchSpec, adopted: bool) -> None:
        try:
            self._supervise_loop(handle, spec, adopted)
        except Exception as exc:  # noqa: BLE001 — 看护线程死了就再没人管这个进程:记下来,停在「起不来」
            logger.exception("本机服务 %s 的看护线程出错", self.instance_id)
            with self._cond:
                if not self._stop.is_set():
                    current = self._handle
                    if current is not None and current.alive():
                        current.kill()
                    self._fail_locked(LocalServiceError("localServiceErr_spawnFailed", detail=str(exc)))

    def _supervise_loop(self, handle: _Handle, spec: LaunchSpec, adopted: bool) -> None:
        restarting = False
        while True:
            if adopted:
                adopted = False
                self._watch(handle)
            else:
                outcome = self._await_ready(handle, spec)
                if outcome is _Outcome.STOPPING:
                    return
                if outcome is _Outcome.TIMEOUT:
                    handle.kill()
                    handle.wait(5.0)
                    self._fail(LocalServiceError("localServiceErr_readyTimeout", seconds=int(spec.ready_timeout)))
                    return
                if outcome is _Outcome.EXITED and not restarting:
                    self._fail(LocalServiceError("localServiceErr_exitedDuringStart", code=_code(handle)))
                    return
                if outcome is _Outcome.READY:
                    self._became_ready()
                    self._watch(handle)
            if self._stop.is_set():
                return
            # 运行中(或重启的那一次还没就绪时)意外退出了:退避之后重起,窗口里次数够了就停在「起不来」
            delay = self._policy.next_delay(time.monotonic())
            if delay is None:
                self._fail(LocalServiceError("localServiceErr_crashedTooOften", count=MAX_RESTARTS,
                                                     minutes=int(RESTART_WINDOW_SECONDS // 60)))
                return
            logger.warning("本机服务 %s 意外退出(退出码 %s),%.0f 秒后重起", self.instance_id, _code(handle), delay)
            with self._cond:
                self._set_locked(RESTARTING)
            if self._stop.wait(delay):
                return
            try:
                spec = self._respawn() if self._respawn is not None else spec
            except Exception as exc:  # noqa: BLE001 — 问不到新的起法(插件说目录不对了):停在「起不来」,原因照说
                self._fail(LocalServiceError.relay(exc) if isinstance(exc, LocalizedError) else
                           LocalServiceError("localServiceErr_spawnFailed", detail=str(exc)))
                return
            with self._cond:
                if self._stop.is_set():
                    return
                try:
                    handle = self._spawn(spec, fresh=False)
                except OSError as exc:
                    self._fail_locked(LocalServiceError("localServiceErr_spawnFailed", detail=str(exc)))
                    return
            restarting = True

    def _await_ready(self, handle: _Handle, spec: LaunchSpec) -> _Outcome:
        deadline = time.monotonic() + spec.ready_timeout
        while True:
            if self._stop.is_set():
                return _Outcome.STOPPING
            if not handle.alive():
                return _Outcome.EXITED
            if healthy(spec.health_url):
                return _Outcome.READY
            if time.monotonic() >= deadline:
                return _Outcome.TIMEOUT
            self.log.pump()
            self._stop.wait(HEALTH_POLL_SECONDS)

    def _watch(self, handle: _Handle) -> None:
        """运行中:等到它退出,或者有人要停它。"""
        while not self._stop.is_set():
            if handle.wait(WATCH_SECONDS):
                return
            self.log.pump()

    def _became_ready(self) -> None:
        with self._cond:
            self.ready_seconds = round(time.monotonic() - self._spawned_at, 1)
            self._set_locked(RUNNING)
            callback = self.on_ready
        logger.info("本机服务 %s 就绪(%.1f 秒)", self.instance_id, self.ready_seconds or 0)
        if callback is not None:
            threading.Thread(target=_quietly, args=(callback, self.instance_id), daemon=True,
                             name=f"local-service-ready-{self.instance_id[:8]}").start()

    # ---- 状态 ----

    def _spawn(self, spec: LaunchSpec, *, fresh: bool) -> _Handle:
        log_file = self.log.open_for_child(fresh=fresh)
        try:
            popen = spawn_to_file(spec.argv, log=log_file, cwd=spec.cwd, env=spec.env)
        finally:
            log_file.close()
        now = datetime.now(UTC)
        self._spawned_at = time.monotonic()
        self.ready_timeout = spec.ready_timeout
        self._handle = _Handle(popen.pid, popen)
        self.pid, self.port, self.started_at, self.adopted = popen.pid, spec.port, now, False
        pidfiles.write(pidfiles.PidRecord(
            instance_id=self.instance_id, pid=popen.pid, argv=list(spec.argv), port=spec.port,
            health_path=spec.health_path, started_at=now.isoformat(), directory=spec.directory, cwd=spec.cwd,
        ))
        return self._handle

    def _fail(self, error: LocalizedError) -> None:
        with self._cond:
            if self._stop.is_set():
                return  # 有人在停它:停完是「已停止」,不是「起不来」
            self._fail_locked(error)

    def _fail_locked(self, error: LocalizedError) -> None:
        self.error = error
        self.failure_lines = self.log.tail(FAILURE_TAIL_LINES)
        logger.warning("本机服务 %s 起不来:%s", self.instance_id, error)
        self._finish_locked(FAILED)

    def _finish_locked(self, state: str) -> None:
        self._handle = None
        self.pid = None
        pidfiles.remove(self.instance_id)
        release(self.instance_id)
        self._set_locked(state)

    def _set_locked(self, state: str) -> None:
        self.state = state
        self._cond.notify_all()


def _code(handle: _Handle) -> str:
    code = handle.exit_code()
    return "?" if code is None else str(code)


def _quietly(callback: Callable[[], None], instance_id: str) -> None:
    try:
        callback()
    except Exception:  # noqa: BLE001 — 就绪之后跟着做的事(刷新目录)失败,不该影响服务本身
        logger.exception("本机服务 %s 就绪之后的回调出错", instance_id)


def _parse_time(raw: str) -> datetime | None:
    try:
        return datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# 这个后端进程里的全部本机服务,和「同一个目录只起一份」
# ---------------------------------------------------------------------------

_services: dict[str, ServiceProcess] = {}
#: 目录的真实路径 → 正在用它的连接。两个连接指同一个目录,第二个直接说「这个目录已经由某某连接在跑」。
_directories: dict[str, str] = {}
_registry_lock = threading.Lock()


def get(instance_id: str) -> ServiceProcess | None:
    with _registry_lock:
        return _services.get(instance_id)


def ensure(instance_id: str, log: ServiceLog) -> ServiceProcess:
    """这个连接的那一个(没有就建)。"""
    with _registry_lock:
        service = _services.get(instance_id)
        if service is None:
            service = ServiceProcess(instance_id, log)
            _services[instance_id] = service
        return service


def everyone() -> list[ServiceProcess]:
    with _registry_lock:
        return list(_services.values())


def claim(instance_id: str, directory_key: str) -> str | None:
    """占下这个目录。已经被**另一个正在跑**的连接占着就回那个连接的 id(不占);占到了回 None。"""
    with _registry_lock:
        holder = _directories.get(directory_key)
        if holder and holder != instance_id:
            other = _services.get(holder)
            if other is not None and other.active:
                return holder
        for key in [key for key, owner in _directories.items() if owner == instance_id]:
            del _directories[key]
        _directories[directory_key] = instance_id
        service = _services.get(instance_id)
        if service is not None:
            service.directory_key = directory_key
        return None


def release(instance_id: str) -> None:
    """放开这个连接占着的目录(停了、起不来了、还没起成就放弃了)。"""
    with _registry_lock:
        for key in [key for key, owner in _directories.items() if owner == instance_id]:
            del _directories[key]


def forget(instance_id: str) -> None:
    """连接删掉了:停掉它(如果在跑),从表里拿掉。"""
    service = get(instance_id)
    if service is not None:
        service.stop()
    with _registry_lock:
        _services.pop(instance_id, None)
    release(instance_id)


__all__ = [
    "ACTIVE", "DEFAULT_READY_TIMEOUT", "FAILED", "LaunchSpec", "RESTARTING", "RUNNING", "Respawn", "RestartPolicy",
    "STARTING", "STATES", "STOPPED", "ServiceProcess", "claim", "ensure", "everyone", "forget", "get", "healthy",
    "port_in_use", "release",
]
