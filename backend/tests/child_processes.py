"""测试进程起的子进程:记下来,会话结束时还在跑的连同它们的进程组一起收掉(tests/conftest.py 接上)。

测试里起子进程的地方很多:插件、本机服务的假服务、各种「睡 60 秒假装卡住」的替身。正常情况下各自的测试会收,但
测试半路失败、忘了收、或者 Ctrl-C 打断时,它们比测试进程活得久 —— 起在新会话里的(看护、插件运行时都这么起,好按组停)
收不到发给测试进程的信号。这里在会话收尾时兜一次底。

测试进程被 kill -9 的时候这里也跑不到:一直不退的那种替身得自己跟着测试进程走(见 fake_local_service 的 `_follow_owner`)。
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading

_spawned: list[int] = []
_lock = threading.Lock()
_installed = False


def track() -> None:
    """从现在起,这个进程里经 `subprocess.Popen` 起的子进程都记下 pid(asyncio 的子进程底下也是它)。幂等。"""
    global _installed
    if _installed:
        return
    _installed = True
    real_init = subprocess.Popen.__init__

    def init(self, *args, **kwargs) -> None:
        real_init(self, *args, **kwargs)
        with _lock:
            _spawned.append(self.pid)

    subprocess.Popen.__init__ = init


def spawned() -> list[int]:
    with _lock:
        return list(_spawned)


def sweep(pids: list[int] | None = None) -> list[int]:
    """收掉还在跑的那些(缺省是记下的全部),交回收掉的 pid。

    只碰**还是自己子进程**的:先 `waitpid(WNOHANG)` 问一句 —— 早就收过的(号可能已经给了别人)问不到,跳过。
    自己是一个进程组的组长(起在新会话里)就整组杀,它起的孙进程一起走。
    """
    if os.name != "posix":
        return []
    killed: list[int] = []
    for pid in pids if pids is not None else spawned():
        try:
            finished, _ = os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            continue  # 已经被收过了
        if finished:
            continue  # 刚好自己退了,这一下顺手收掉
        try:
            if os.getpgid(pid) == pid:
                os.killpg(pid, signal.SIGKILL)
            else:
                os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            continue
        try:
            os.waitpid(pid, 0)
        except ChildProcessError:
            pass
        killed.append(pid)
    return killed
