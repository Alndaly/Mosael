"""常驻 worker 的「宿主没了就跟着退」。合成、识别共用这一份。

常驻进程最坏的下场是变成孤儿:后端被强杀或热重载,它还抱着几个 GB 的权重躺在那儿,没有任何东西会去收它
(现场抓到过一个 PPID=1、抱着 2.2 GB 跑了 35 分钟的)。stdin 关闭是常规信号,但一个正卡在下载里的 worker
要等下载完才读得到 EOF,所以另起一条线程盯着宿主。

**判据是「宿主进程还在不在」,而且绝不对它发信号。** 此前识别那边每 5 秒 `os.kill(宿主pid, 0)`:POSIX 上
无害,Windows 上 signal 0 就是 CTRL_C_EVENT,CPython 会去调 GenerateConsoleCtrlEvent —— 要么调用失败、worker
当成宿主没了自己退(常驻识别起来几秒就没了,转写反复失败),要么把 Ctrl+C 发给同一个控制台里的后端
(见 core/child_process._windows_process_alive 的说明)。合成那边比 getppid,Windows 上不伤人,但也不起作用:
Windows 不会把孤儿过继给别人,getppid 永远是当初那个数。

- POSIX:宿主一死,这个进程被过继给 init(或某个 subreaper),getppid 就变了;
- Windows:一开始就拿住宿主的进程句柄,之后问它的退出码(OpenProcess + GetExitCodeProcess,写法同
  core/child_process._windows_process_alive)。句柄一直握着,所以宿主退出后那个 pid 即使被新进程复用,
  问到的也还是原来那个进程。

和 workers/ 下别的文件一样:stdlib-only,不许 import ``app.*``(见 workers/__init__.py)。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from collections.abc import Callable
from typing import Any

#: GetExitCodeProcess 对还在跑的进程返回的「退出码」。
STILL_ACTIVE = 259
_SYNCHRONIZE = 0x00100000
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _posix_probe(parent_pid: int) -> Callable[[], bool]:
    return lambda: os.getppid() == parent_pid


def _windows_probe(parent_pid: int, kernel32: Any) -> Callable[[], bool]:
    """握着宿主的进程句柄问它的退出码。打不开(宿主已经没了)就当它不在。"""
    import ctypes

    handle = kernel32.OpenProcess(_SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, parent_pid)
    if not handle:
        return lambda: False

    def alive() -> bool:
        code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            # 问不出来不等于宿主没了:这时退出,丢掉的是一份载好的权重;留着,最坏是多活一会儿。
            return True
        return code.value == STILL_ACTIVE

    return alive


def parent_probe(parent_pid: int, *, platform: str = sys.platform, kernel32: Any = None) -> Callable[[], bool]:
    """「宿主还在吗」的探针。`platform`、`kernel32` 只为测试替换。"""
    if platform == "win32":
        if kernel32 is None:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        return _windows_probe(parent_pid, kernel32)
    return _posix_probe(parent_pid)


def watch_parent(
    *,
    interval: float = 1.0,
    probe: Callable[[], bool] | None = None,
    on_gone: Callable[[], None] = lambda: os._exit(0),
) -> threading.Thread:
    """起一条守护线程:宿主没了就立刻退出。

    不做清理(`os._exit`):权重还挂在内存里,越快还给系统越好。线程本身不能因为一次意外死掉 —— 它一死,
    孤儿进程就回来了,而没人会发现。
    """
    alive = probe or parent_probe(os.getppid())

    def run() -> None:
        while True:
            try:
                time.sleep(interval)
                if not alive():
                    on_gone()
                    return
            except Exception:  # noqa: BLE001 — 见上
                time.sleep(5.0)

    thread = threading.Thread(target=run, daemon=True, name="parent-watch")
    thread.start()
    return thread
