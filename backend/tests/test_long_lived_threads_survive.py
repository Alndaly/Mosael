"""常驻的那几个线程,不能因为一次意外就无声地死掉。

它们的共同点是**没人等它们**:没有 join、没有 future,一旦线程里抛出异常,Python 把
traceback 打到 stderr 就完了,而它负责的事从此不再发生 —— 没有任何东西会变红。

具体后果:

- `_drain_stderr` 死了 → 没人读子进程的 stderr → 管道写满 → **worker 永远卡在 write 上**。
  这正是 core/child_process 开头记的那个"同一个错误在四个地方各犯一次"的死锁。
- `_reap_idle` 死了 → 闲置的合成进程再也不会被放掉 → 18 GB 一直占着。
- worker 里的 `_watch_parent` 死了 → 后端重启后又开始攒孤儿进程。

判据不是"不出错",是**出错之后它还在**。
"""

from __future__ import annotations

import sys
import textwrap
import time

from app.audio import tts_daemon


def test_the_reaper_survives_a_bad_worker_entry(tmp_path) -> None:
    """回收线程遇到一次意外要继续跑 —— 它一死,闲置的几个 GB 就再也回不来。

    坏条目要**先**放进去:放在正常 worker 之后的话,那个 worker 可能在线程死掉之前就已经被
    回收了,测试于是靠时序侥幸通过(第一版就是这样,把护栏拿掉照样绿)。
    """
    script = tmp_path / "w.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import json, sys
            for line in sys.stdin:
                if line.strip():
                    sys.stdout.write({tts_daemon.EVENT_PREFIX!r} + json.dumps({{"event": "done"}}) + "\\n")
                    sys.stdout.flush()
            """
        ),
        encoding="utf-8",
    )
    pool = tts_daemon.WorkerPool(worker_path=str(script), idle_seconds=0.3)
    try:
        # 先埋雷:一个没有 busy / last_used 的东西,回收那一轮会在它身上抛。
        with pool._lock:
            pool._workers[("broken", "x")] = object()  # type: ignore[assignment]
        time.sleep(1.5)  # 让回收线程撞上它几次

        pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"}, timeout=20)
        deadline = time.time() + 6
        while pool.alive("fish-speech", sys.executable) and time.time() < deadline:
            time.sleep(0.1)

        assert not pool.alive("fish-speech", sys.executable), (
            "回收线程被那个坏条目弄死了 —— 之后闲置的进程再也不会被放掉"
        )
    finally:
        pool.shutdown()


def test_the_stderr_drain_survives_bad_bytes(tmp_path) -> None:
    """子进程往 stderr 写什么都可能 —— 排空线程死了就等于**死锁**:管道写满,子进程卡在 write。

    这里必须写**超过一个管道缓冲区**(约 64KB)的量,否则子进程写完就走,测不出"没人排空"
    的后果 —— 第一版只写了 2.6KB,把护栏拿掉照样绿,那是一条什么都没测的测试。
    """
    script = tmp_path / "noisy.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import json, sys
            # 1 MB 非法 UTF-8:远超管道缓冲区,没人读就会把子进程卡在 write 上。
            sys.stderr.buffer.write(b"\\xff\\xfe not utf8 " * 60000)
            sys.stderr.flush()
            for line in sys.stdin:
                if line.strip():
                    sys.stdout.write({tts_daemon.EVENT_PREFIX!r} + json.dumps({{"event": "done", "ok": True}}) + "\\n")
                    sys.stdout.flush()
            """
        ),
        encoding="utf-8",
    )
    pool = tts_daemon.WorkerPool(worker_path=str(script))
    try:
        result = pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"}, timeout=15)
        assert result["ok"] is True
    finally:
        pool.shutdown()
