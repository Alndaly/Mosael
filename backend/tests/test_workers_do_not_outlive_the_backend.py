"""后端没了,常驻 worker 也该走。

现场抓到的:

    worker 25206  父进程=1  内存 2.2 GB  已跑 35 分钟

父进程是 1 说明它是**孤儿** —— 后端热重载(开发时每改一次文件就重启一次)把池子连同
kill() 一起带走了,而子进程没人管,抱着两三个 GB 继续活着。开发机上一天能攒出好几个;
打包版虽然不带 reload,但后端崩溃/被杀也是一样的形状。

不能指望"父进程记得清理":父进程被 SIGKILL 时不会执行任何清理代码。**得让子进程自己看着。**
stdin 关闭是常规信号(父进程一死管道就断),但一个正卡在下载里的 worker 要等下载结束才会
读到 EOF —— 所以再加一条:看门狗线程盯着 getppid(),被过继给 init 就自己退出。
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

WORKER = Path(__file__).resolve().parents[1] / "app" / "ai" / "runtime" / "workers" / "tts.py"


def test_the_worker_exits_when_its_parent_dies(tmp_path) -> None:
    """起一个中间父进程 → 它起 worker → 杀掉中间父进程 → worker 该自己走。"""
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        textwrap.dedent(
            f"""
            import subprocess, sys, time
            child = subprocess.Popen([sys.executable, {str(WORKER)!r}, "--serve"],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            print(child.pid, flush=True)
            time.sleep(120)
            """
        ),
        encoding="utf-8",
    )
    parent = subprocess.Popen([sys.executable, str(launcher)], stdout=subprocess.PIPE, text=True)
    try:
        worker_pid = int(parent.stdout.readline().strip())
        parent.kill()
        parent.wait(10)

        deadline = time.time() + 20
        while time.time() < deadline:
            try:
                os.kill(worker_pid, 0)
            except OSError:
                return  # 走了
            time.sleep(0.5)
        os.kill(worker_pid, 9)
        raise AssertionError("父进程死了 20 秒,worker 还抱着几个 GB 活着")
    finally:
        if parent.poll() is None:
            parent.kill()


def test_the_watchdog_is_installed_in_serve_mode() -> None:
    """判据挂在**常驻模式**上 —— 一次性模式跑完就退,不需要看门狗。"""
    source = WORKER.read_text(encoding="utf-8")

    assert "getppid" in source, "没有人盯着父进程"
