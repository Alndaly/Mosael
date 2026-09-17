"""「正在下 / 刚下失败」和「探过没探过」—— 本机引擎那几条路共用的两小块内存状态。

**静息时的事实源在盘上**(文件在不在、解释器跑不跑得起来);这里只在"正在下"和"刚失败"时
有话说,重启丢掉的是"有人正在下"这句话,而那个下载线程本来就随进程一起没了。

此前转写模型、克隆引擎、克隆权重各抄了一份(两份逐字相同,第三份换成了字典),而其中一条踩过的
坑只修在了那一条上 —— 探测的**代次**:清缓存时不记代次的话,上一代在飞的探测要么永远占着
"正在探测"、要么把过期答案写回来(见 ProbeCache)。抄一份就是把这种修复留在原地。
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DownloadProgress:
    status: str = "idle"  # "downloading" | "failed"
    downloaded: int = 0
    total: int = 0
    speed: float = 0.0  # bytes/sec
    eta: float | None = None  # seconds remaining
    #: 0..1。按字节报不出进度的阶段(装运行环境跑的是 pip)用它,或者反过来。
    progress: float = 0.0
    message: str = ""
    #: message 是 i18n key 时的模板参数。翻译在出口做,这里只负责把值带出来。
    params: dict[str, str] = field(default_factory=dict)
    error: str = ""


class DownloadStore:
    """一个引擎/一份权重一条记录。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live: dict[str, DownloadProgress] = {}

    def get(self, key: str) -> DownloadProgress | None:
        with self._lock:
            live = self._live.get(key)
            return None if live is None else DownloadProgress(**live.__dict__)

    def set(self, key: str, live: DownloadProgress) -> None:
        with self._lock:
            self._live[key] = live

    def merge(self, key: str, **fields: Any) -> None:
        """只改几个字段,其余保持原样(边下边报进度的那条路)。"""
        with self._lock:
            live = self._live.get(key) or DownloadProgress()
            for name, value in fields.items():
                setattr(live, name, value)
            self._live[key] = live

    def clear(self, key: str) -> None:
        with self._lock:
            self._live.pop(key, None)

    def reset(self) -> None:
        """全清(测试之间用)。一个用例留下的 "downloading" 会让下一个读到别人的状态,而
        start_download 还会据此拒绝服务(「已有模型正在下载」)。"""
        with self._lock:
            self._live.clear()

    def downloading(self) -> bool:
        return bool(self.busy_key())

    def busy_key(self) -> str:
        """正在下的那一个(没有就是空串)。一次只下一个:这些文件都是 GB 级,并发下只会互相抢带宽。"""
        with self._lock:
            return next((key for key, live in self._live.items() if live.status == "downloading"), "")


class ProbeCache:
    """「这个引擎跑不跑得起来」的答案。探一次要起子进程,而列状态是一次纯读的请求。

    **列状态只读缓存、永远不等**:没探过就先说"还没测过",后台去问。"还没测过"和"测过了、
    跑不起来"是两回事 —— 把前者说成后者,就是拿一个未知冒充一个结论。

    `invalidate()` 记**代次**:在飞的探测因此成了上一代,既不占着"正在探测"的位置,结果也不会
    写回来(它探的是改配置之前那套环境)。两种失败都真实发生过。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._known: dict[str, Any] = {}
        self._probing: set[str] = set()
        self._generation = 0

    def known(self, key: str) -> tuple[Any, bool]:
        """(记着的答案, 测过了吗)。"""
        with self._lock:
            return (self._known.get(key), key in self._known)

    def remember(self, key: str, value: Any) -> Any:
        with self._lock:
            self._known[key] = value
        return value

    def invalidate(self) -> None:
        with self._lock:
            self._known.clear()
            self._probing.clear()
            self._generation += 1

    def probe_in_background(self, key: str, probe: Callable[[], Any]) -> None:
        """确保这个 key 被探过一次。已经在探的不重复起线程。"""
        with self._lock:
            if key in self._known or key in self._probing:
                return
            self._probing.add(key)
            generation = self._generation

        def run() -> None:
            value = None
            try:
                value = probe()
            finally:
                with self._lock:
                    if generation == self._generation:
                        self._probing.discard(key)
                        self._known[key] = value

        threading.Thread(target=run, daemon=True, name="runtime-probe").start()
