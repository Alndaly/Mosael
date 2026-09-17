"""「正在装 / 刚装失败」这句话 —— 本机引擎安装进度的内存那一半。

**静息时的事实源在盘上**(解释器、二进制在不在),这里只在"正在装"和"刚失败"时有话说:
重启丢掉的是"有人正在装"这句话,而那个安装线程本来就随进程一起没了。

分离引擎(托管 venv)和降噪引擎(下载的二进制)各有一份实例,形状一样 —— 此前是
separation_models 里的私有类,第二个用它的地方出现时抽到这里,免得抄一份。
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

INSTALLING = "installing"
FAILED = "failed"


@dataclass
class InstallProgress:
    status: str = "idle"  # INSTALLING | FAILED
    #: 可以是 i18n key(配 params,在出口翻译),也可以是一句原样的失败原因。
    message: str = ""
    params: dict[str, str] = field(default_factory=dict)


class InstallStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._live: dict[str, InstallProgress] = {}

    def get(self, engine: str) -> InstallProgress | None:
        with self._lock:
            live = self._live.get(engine)
            return None if live is None else InstallProgress(live.status, live.message, dict(live.params))

    def set(self, engine: str, progress: InstallProgress) -> None:
        with self._lock:
            self._live[engine] = progress

    def clear(self, engine: str) -> None:
        with self._lock:
            self._live.pop(engine, None)

    def begin(self, engine: str, message: str, **params: str) -> None:
        """标成"正在装"。已经在装就拒 —— 两个线程同时装同一个东西会互相踩。"""
        with self._lock:
            live = self._live.get(engine)
            if live is not None and live.status == INSTALLING:
                raise RuntimeError("这个引擎已经在安装中")
            self._live[engine] = InstallProgress(INSTALLING, message, dict(params))

    def status_fields(self, engine: str, *, ready: bool) -> dict[str, Any]:
        """给设置页的那几个字段。装好了就是 installed,不管内存里记着什么。"""
        live = self.get(engine)
        status = "installed" if ready else "missing"
        if live is not None and live.status in {INSTALLING, FAILED} and not ready:
            status = live.status
        return {
            "status": status,
            "message": live.message if live else "",
            "message_params": dict(live.params) if live else {},
        }
