"""ChildProcess 的 stderr 排空线程死了 = 子进程卡死。

这个类的开头就记着那个教训:「同一个错误在四个地方各犯一次:给子进程 stderr=PIPE,读 stdout,
读完才读 stderr。子进程往 stderr 写超过一个管道缓冲区(约 64KB)就卡在 write 上,而父进程
卡在 read stdout 上,谁都动不了。」

它用一个线程一直排空 stderr 来解决。但那个线程**自己没有护栏**:

    for line in self._process.stderr:      # ← 解码失败就抛,线程就死
        self._stderr.append(line)

子进程往 stderr 写的东西不由我们决定:ffmpeg 在坏源上逐帧报错、pip 打进度条、torch 打警告,
其中任何一段非法字节都会让这个线程死掉 —— 然后就退回到它当初要解决的那个死锁。

它服务的正是最长、最吵的那几个:渲染导出、模型下载、智能体 sidecar。

(我刚在 tts_daemon 里修过同一个形状,而这一份是更早、用得更广的那个。)
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
import time

from app.core.child_process import ChildProcess


def _noisy_child(tmp_path, mb: int = 1) -> subprocess.Popen:
    script = tmp_path / "noisy.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import sys, time
            # 非法 UTF-8,量超过一个管道缓冲区:没人排空就会把子进程卡在 write 上。
            sys.stderr.buffer.write(b"\\xff\\xfe bad " * {mb * 100000})
            sys.stderr.flush()
            print("done", flush=True)
            """
        ),
        encoding="utf-8",
    )
    return subprocess.Popen(
        [sys.executable, str(script)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1,
    )


def test_a_child_writing_garbage_to_stderr_still_finishes(tmp_path) -> None:
    child = ChildProcess(_noisy_child(tmp_path), timeout=20)
    began = time.monotonic()

    lines = list(child.lines())
    child.finish(10)

    assert any("done" in line for line in lines), f"子进程没能写完 stdout:{lines}"
    assert time.monotonic() - began < 15, "卡住了 —— 排空线程死了,子进程堵在 write 上"


def test_the_drain_thread_survives_a_decode_error(tmp_path) -> None:
    """线程本身要活到子进程结束 —— 它一死,后面所有 stderr 都没人读。"""
    child = ChildProcess(_noisy_child(tmp_path), timeout=20)
    list(child.lines())
    child.finish(10)

    assert not child._drain.is_alive(), "排空线程该在子进程结束后自然退出"
