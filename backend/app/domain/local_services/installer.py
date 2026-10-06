"""让 Mosael 装(ADR 0041 §4)的宿主那一半:一次安装在后台线程里跑,进度在内存里(界面按 1200 ms 轮询,和引擎安装一样)。

插件做前面几步(查空间、下源码、解开、建 venv、装 PyTorch、装依赖、装 pysssss —— 见插件的 `service_install`),每一步做完
它自己在安装目录里记一笔;**最后一步「试起一次」是宿主的**(进程归宿主管),怎么做由 `local_services` 交进来(`work`)。
这里只管这一次安装的状态:到了哪一步、多少字节、多快、成没成、取消。

- **取消**:拉下这一次的开关 → 运行时建取消文件 → 插件停在手上那一步(下次从它开始);试起那一步取消就是停下它。
- **进度不落库**:后端重启后内存里没了,磁盘上的安装记录还在 —— 连接页按安装计划摆出哪几步做完了,点「接着装」。
- **速度**由宿主按字节和时间算(同一步、同一个文件里两次之间下了多少),插件只报字节。
- **换版本也是这样一次**(`kind`:`update` 更新到某个钉死版本、`rollback` 回到上一版):插件那几步换源码、装依赖,宿主试起一次;
  同一个连接同一时刻只有一次(装、更新、回退互斥),进度、取消、日志都是同一套。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.i18n import LocalizedError, get_current_locale, tr
from app.core.rate import DownloadRate
from app.domain.local_services.errors import LocalServiceError
from app.domain.local_services.logs import ServiceLog
from app.domain.plugins.manifest import text_of
from app.domain.plugins.runtime import PluginCancelled

logger = logging.getLogger(__name__)

INSTALLING = "installing"
SUCCEEDED = "succeeded"
FAILED = "failed"
CANCELLED = "cancelled"
STATES = (INSTALLING, SUCCEEDED, FAILED, CANCELLED)
#: 这一次在做什么:装(或接着装、重建运行环境)、更新到更新的钉死版本、回到上一版。
INSTALL = "install"
UPDATE = "update"
ROLLBACK = "rollback"
KINDS = (INSTALL, UPDATE, ROLLBACK)
#: 宿主自己的那一步(插件的几步之后),按这一次在做什么说。
TRIAL = "trial"
TRIAL_TITLES = {
    INSTALL: "localServiceInstall_trial",
    UPDATE: "localServiceUpdate_trial",
    ROLLBACK: "localServiceRollback_trial",
}
#: 一份安装计划最多几步(插件说的,再加宿主那一步)。
MAX_STEPS = 20
#: 算速度的平滑:这么多秒之前的样本权重减半(core/rate,和别的下载同一个算法)。
SPEED_HALF_LIFE_SECONDS = 3.0
#: 后端退出时等正在装的停下最多多久(插件收到取消文件后停掉 pip,一般一两秒)。
SHUTDOWN_WAIT_SECONDS = 15.0


class InstallCancelled(Exception):
    """这一次安装被取消了(试起那一步里看到的;插件那几步里是运行时的 PluginCancelled)。"""


@dataclass
class _Step:
    key: str
    #: 插件写的(字符串或按语言分的);宿主那一步是 None,读的时候按读的人的语言取文案。
    title: Any
    done: bool = False


class InstallRun:
    """一个连接这一次安装。线程安全:安装线程写,看状态的请求读。"""

    def __init__(self, instance_id: str, log: ServiceLog, *, author_locale: str, kind: str = INSTALL, target: str = "") -> None:
        self.instance_id = instance_id
        self.log = log
        self.author_locale = author_locale
        #: 装、更新、回退;更新 / 回退时换到哪个版本(界面上写「正在更新到 0.39.0」)。
        self.kind = kind
        self.target = target
        self.state = INSTALLING
        self.steps: list[_Step] = []
        self.current = ""
        self.done_bytes: int | None = None
        self.total_bytes: int | None = None
        #: 这一步手上的是哪个(文件名,或插件说的一句话)。
        self.item: Any = None
        #: 字节每秒(平滑过的);没在下东西时是 None。
        self.speed: float | None = None
        self.error: LocalizedError | None = None
        self.started_at = datetime.now(UTC)
        self.finished_at: datetime | None = None
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None
        self._lock = threading.Lock()
        #: 正在量速度的那一个(这一步、这个文件)和它的速率。
        self._measuring: tuple[str, Any] | None = None
        self._rate = DownloadRate(half_life=SPEED_HALF_LIFE_SECONDS)

    # ---- 插件说的(安装线程里) ----

    def on_step(self, event: dict[str, Any]) -> None:
        """插件的一行 `{"event": "step", …}`:开头那一行说有哪几步(`outline`),之后每一步开始、进行中、做完。"""
        with self._lock:
            outline = event.get("outline")
            if isinstance(outline, list):
                self.steps = [_Step(str(one["key"])[:40], one.get("title"), one.get("done") is True)
                              for one in outline[: MAX_STEPS - 1] if isinstance(one, dict) and one.get("key")]
                self.steps.append(_Step(TRIAL, None))
                return
            key = str(event.get("key") or "")[:40]
            if not key:
                return
            step = self._step(key)
            if event.get("state") == "done":
                step.done = True
                if self.current == key:
                    self._clear_progress()
                return
            if self.current != key:
                self.current = key
                self._clear_progress()
            item = event.get("item")
            done, total = _count(event.get("done_bytes")), _count(event.get("total_bytes"))
            self.item, self.done_bytes, self.total_bytes = item, done, total
            self._measure(key, item, done)

    def begin_trial(self) -> None:
        with self._lock:
            self._step(TRIAL)
            self.current = TRIAL
            self._clear_progress()

    def say(self, item: dict[str, str]) -> None:
        """宿主在手上这一步里说一句(按语言分着给):试起没通过、正在换回上一版时。"""
        with self._lock:
            self._clear_progress()
            self.item = item

    def _step(self, key: str) -> _Step:
        found = next((one for one in self.steps if one.key == key), None)
        if found is None:
            found = _Step(key, None)
            # 插件没先说有哪几步:按出现的先后排,宿主那一步总在最后
            at = len(self.steps) - 1 if self.steps and self.steps[-1].key == TRIAL and key != TRIAL else len(self.steps)
            self.steps.insert(at, found)
        return found

    def _clear_progress(self) -> None:
        self.item, self.done_bytes, self.total_bytes, self.speed, self._measuring = None, None, None, None, None

    def _measure(self, key: str, item: Any, done: int | None) -> None:
        """同一步、同一个文件的字节 → 速度(core/rate 的滑动平均,抖动磨平)。换了文件就重新开始量。"""
        if done is None:
            return
        if self._measuring != (key, item):
            self._measuring, self._rate, self.speed = (key, item), DownloadRate(half_life=SPEED_HALF_LIFE_SECONDS), None
        speed = self._rate.update(done, at=time.monotonic())
        self.speed = speed if speed > 0 else None

    # ---- 收尾 ----

    def finish(self, state: str, error: LocalizedError | None = None) -> None:
        with self._lock:
            self.state, self.error, self.finished_at = state, error, datetime.now(UTC)
            if state == SUCCEEDED:
                for step in self.steps:
                    step.done = True
            self._clear_progress()
            self.current = "" if state == SUCCEEDED else self.current

    # ---- 给界面看的 ----

    def snapshot(self) -> dict[str, Any]:
        """按看的人的语言整理好(插件写的标题按语言挑,宿主那一步取文案)。"""
        locale = get_current_locale()
        with self._lock:
            def said(value: Any) -> str:
                return text_of(value, locale, author_locale=self.author_locale).strip()[:300] if value else ""

            return {
                "kind": self.kind,
                "target": self.target,
                "state": self.state,
                "step": self.current,
                "steps": [{"key": one.key, "title": tr(TRIAL_TITLES[self.kind]) if one.key == TRIAL else said(one.title),
                           "done": one.done} for one in self.steps],
                "done_bytes": self.done_bytes,
                "total_bytes": self.total_bytes,
                "item": said(self.item),
                "speed": int(self.speed) if self.speed is not None else None,
                "error": str(self.error) if self.error is not None else "",
                "started_at": self.started_at.isoformat(),
                "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            }


def _count(value: Any) -> int | None:
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value >= 0 else None


# ---------------------------------------------------------------------------
# 这个后端进程里的全部安装
# ---------------------------------------------------------------------------

_runs: dict[str, InstallRun] = {}
_registry_lock = threading.Lock()


def current(instance_id: str) -> InstallRun | None:
    """这个连接最近的一次安装(装着的,或者结束了还没被下一次替掉的)。"""
    with _registry_lock:
        return _runs.get(instance_id)


def installing(instance_id: str) -> bool:
    run = current(instance_id)
    return run is not None and run.state == INSTALLING


def begin(
    instance_id: str, log_path: Path, *, author_locale: str, work: Callable[[InstallRun], None], kind: str = INSTALL,
    target: str = "",
) -> InstallRun:
    """开一次安装(或换版本,见 `kind`):日志先滚一份(上一次的留成 `.1`),起后台线程跑 `work(run)`。已经在装(或在换)就拒。

    `work` 正常返回 = 装好了;抛 PluginCancelled / InstallCancelled = 取消了;抛别的 = 没装成(原因照说)。"""
    with _registry_lock:
        existing = _runs.get(instance_id)
        if existing is not None and existing.state == INSTALLING:
            raise LocalServiceError("localServiceErr_installing")
        log = ServiceLog(log_path)
        log.open_for_child(fresh=True).close()
        run = InstallRun(instance_id, log, author_locale=author_locale, kind=kind, target=target)
        _runs[instance_id] = run
    run.thread = threading.Thread(target=_run, args=(run, work), daemon=True, name=f"local-service-install-{instance_id[:8]}")
    run.thread.start()
    return run


def _run(run: InstallRun, work: Callable[[InstallRun], None]) -> None:
    try:
        work(run)
    except (PluginCancelled, InstallCancelled):
        run.finish(CANCELLED)
        logger.info("本机服务 %s 的这一次(%s)取消了", run.instance_id, run.kind)
    except LocalizedError as exc:
        run.finish(FAILED, exc)
        logger.warning("本机服务 %s 这一次(%s)没成:%s", run.instance_id, run.kind, exc)
    except Exception as exc:  # noqa: BLE001 — 安装线程里的意外:记下来,停在「没装成」,原因照说
        logger.exception("本机服务 %s 这一次(%s)出错", run.instance_id, run.kind)
        run.finish(FAILED, LocalServiceError("localServiceErr_installCrashed", detail=f"{type(exc).__name__}: {exc}"))
    else:
        run.finish(SUCCEEDED)
        logger.info("本机服务 %s 这一次(%s)成了", run.instance_id, run.kind)


def cancel(instance_id: str) -> bool:
    """取消这个连接正在跑的安装。没在装回 False。"""
    run = current(instance_id)
    if run is None or run.state != INSTALLING:
        return False
    run.cancel.set()
    return True


def forget(instance_id: str, *, wait: float = SHUTDOWN_WAIT_SECONDS) -> None:
    """连接要删了:正在装的先取消、等它停下,再从表里拿掉。"""
    run = current(instance_id)
    if run is not None:
        run.cancel.set()
        if run.thread is not None and run.thread is not threading.current_thread():
            run.thread.join(timeout=wait)
    with _registry_lock:
        _runs.pop(instance_id, None)


def cancel_all(wait: float = SHUTDOWN_WAIT_SECONDS) -> None:
    """后端退出时:正在装的都取消,等它们停下(插件停掉 pip、记下停在哪一步),最多 `wait` 秒。"""
    with _registry_lock:
        running = [run for run in _runs.values() if run.state == INSTALLING]
    for run in running:
        run.cancel.set()
    deadline = time.monotonic() + wait
    for run in running:
        if run.thread is not None:
            run.thread.join(timeout=max(0.0, deadline - time.monotonic()))


__all__ = [
    "CANCELLED", "FAILED", "INSTALL", "INSTALLING", "KINDS", "ROLLBACK", "InstallCancelled", "InstallRun", "STATES", "SUCCEEDED",
    "TRIAL", "UPDATE", "begin", "cancel", "cancel_all", "current", "forget", "installing",
]
