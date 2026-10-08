"""常驻的识别 / 合成 worker:宿主没了就跟着退,而且**绝不对宿主发信号**(MED-5)。

此前识别 worker 每 5 秒 `os.kill(宿主pid, 0)` 探活。Windows 上 signal 0 就是 CTRL_C_EVENT:要么调用失败、worker
当成宿主没了自己退(常驻识别起来几秒就没了),要么把 Ctrl+C 发给同一个控制台里的后端。合成 worker 比 getppid,
Windows 上不起作用(孤儿不会被过继)。两边现在共用 workers/parent_watch。

Windows 那条路在这里用假的 kernel32 驱动 —— **真机上没跑过**,只验证了「握着句柄问退出码、不发信号」这个写法。
"""

from __future__ import annotations

import ast
import ctypes
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from app.ai.runtime import workers
from app.ai.runtime.workers.parent_watch import STILL_ACTIVE, parent_probe
from app.core.child_process import process_alive

WORKERS_DIR = Path(workers.__file__).resolve().parent


class FakeKernel32:
    """只认 parent_watch 用到的那三个调用。`exit_code` 是宿主此刻的退出码;`None` 表示问不出来。"""

    def __init__(self, *, opens: bool = True) -> None:
        self.opens = opens
        self.exit_code: int | None = STILL_ACTIVE
        self.opened: list[int] = []
        self.closed = 0

    def OpenProcess(self, _access: int, _inherit: bool, pid: int) -> int:  # noqa: N802 — Win32 的名字
        self.opened.append(pid)
        return 7 if self.opens else 0

    def GetExitCodeProcess(self, handle: int, ref) -> int:  # noqa: N802
        assert handle == 7
        if self.exit_code is None:
            return 0
        ref._obj.value = self.exit_code
        return 1

    def CloseHandle(self, _handle: int) -> int:  # noqa: N802
        self.closed += 1
        return 1


@pytest.fixture
def no_signals(monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("探活对宿主发了信号:Windows 上 signal 0 就是 Ctrl+C")

    monkeypatch.setattr(os, "kill", refuse)


def test_Windows上握着宿主句柄问退出码_不对它发信号(no_signals) -> None:
    kernel32 = FakeKernel32()
    alive = parent_probe(4242, platform="win32", kernel32=kernel32)

    assert alive() is True
    kernel32.exit_code = 0
    assert alive() is False

    assert kernel32.opened == [4242], "句柄只开一次、一直握着 —— pid 被复用时问到的还是原来那个进程"
    assert kernel32.closed == 0


def test_Windows上宿主已经没了_打不开句柄就当它不在(no_signals) -> None:
    assert parent_probe(4242, platform="win32", kernel32=FakeKernel32(opens=False))() is False


def test_Windows上问不出退出码_不当成宿主没了(no_signals) -> None:
    """这时退出丢掉的是一份载好的几个 GB 权重;留着,最坏是多活一会儿。"""
    kernel32 = FakeKernel32()
    kernel32.exit_code = None
    assert parent_probe(4242, platform="win32", kernel32=kernel32)() is True


def test_POSIX上看的是自己有没有被过继(no_signals) -> None:
    assert parent_probe(os.getppid(), platform="darwin")() is True
    assert parent_probe(os.getppid() + 1, platform="linux")() is False


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX 的过继语义;Windows 那条见上面的假 kernel32")
def test_宿主被杀_常驻worker几秒内跟着退() -> None:
    """真进程:中间那个进程起一个跑着 watch_parent 的「worker」然后自己退,worker 被过继、随即退出。"""
    worker = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(WORKERS_DIR)!r})  # 和引擎解释器一样:sys.path 上只有 workers/ 这一个目录
        from parent_watch import watch_parent
        watch_parent(interval=0.05)
        print("watching", flush=True)
        time.sleep(30)
    """)
    # 宿主等 worker 说「盯上了」再退:不等的话,worker 还没起来宿主就没了,它记下的「宿主」已经是 init。
    host = textwrap.dedent(f"""
        import subprocess, sys
        child = subprocess.Popen([sys.executable, "-c", {worker!r}], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        child.stdout.readline()
        print(child.pid, flush=True)
    """)
    out = subprocess.run([sys.executable, "-c", host], capture_output=True, text=True, timeout=30, check=True)
    worker_pid = int(out.stdout.strip())
    try:
        deadline = time.monotonic() + 10
        while process_alive(worker_pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert not process_alive(worker_pid), "宿主没了,常驻 worker 还抱着权重躺着"
    finally:
        if process_alive(worker_pid):
            os.kill(worker_pid, 9)


def test_两个常驻worker都用这一份_workers下没有人对别的进程发信号() -> None:
    offenders = []
    for path in sorted(WORKERS_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "kill"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "os"
            ):
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], f"os.kill 在 Windows 上会结束对方或发 Ctrl+C:{offenders}"
    for name in ("asr.py", "tts.py"):
        assert "watch_parent()" in (WORKERS_DIR / name).read_text(encoding="utf-8"), f"{name} 没有跟着宿主走"


def test_假kernel32的写法和ctypes对得上() -> None:
    """byref(...)._obj 是 ctypes 的公开行为之一;它变了,上面几条就在测别的东西。"""
    code = ctypes.c_ulong()
    ctypes.byref(code)._obj.value = 5
    assert code.value == 5
