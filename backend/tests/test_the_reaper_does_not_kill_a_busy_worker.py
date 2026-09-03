"""闲置回收不能把**正在干活**的进程杀掉。

真机验证第一次就撞上了:Fish Speech 首次合成要先加载 511.9 秒权重,而回收线程的判据是
`last_used < 现在 - 600s`。`last_used` 只在请求**开始**和**结束**时更新 —— 于是一个跑了
十分钟的请求,在它还没跑完的时候就被判成"闲置",进程被杀,宿主收到「合成进程中途退出」。

单测没抓到,因为那里的假 worker 立刻就回话:**从来没有一个请求活得比超时更久**。
判据里缺的不是时间,是"它在不在忙"。
"""

from __future__ import annotations

import sys
import textwrap
import time

from app.ai.runtime import tts_daemon
from app.ai.runtime.workers.tts_protocol import EVENT_PREFIX


def _slow_worker(tmp_path) -> str:
    """一个回话很慢的 worker —— 慢过闲置超时。"""
    script = tmp_path / "slow_worker.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import json, sys, time
            PREFIX = {EVENT_PREFIX!r}
            for line in sys.stdin:
                if not line.strip():
                    continue
                request = json.loads(line)
                time.sleep(1.5)
                sys.stdout.write(PREFIX + json.dumps({{"event": "done", "engine": "fish-speech", "output": "ok"}}) + "\\n")
                sys.stdout.flush()
            """
        ),
        encoding="utf-8",
    )
    return str(script)


def test_a_long_request_is_not_reaped(tmp_path) -> None:
    """请求比闲置超时还长时,进程必须活着 —— 首次加载权重就是这个形状(511 秒)。"""
    pool = tts_daemon.WorkerPool(worker_path=_slow_worker(tmp_path), idle_seconds=0.3)
    try:
        result = pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"}, timeout=30)
    finally:
        pool.shutdown()

    assert result["output"] == "ok"


def test_it_is_still_reaped_once_it_goes_idle(tmp_path) -> None:
    """忙的时候不杀,不等于永远不杀 —— 18 GB 闲着还是要还回去。"""
    pool = tts_daemon.WorkerPool(worker_path=_slow_worker(tmp_path), idle_seconds=0.3)
    try:
        pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"}, timeout=30)
        deadline = time.time() + 6
        while pool.alive("fish-speech", sys.executable) and time.time() < deadline:
            time.sleep(0.1)
        assert not pool.alive("fish-speech", sys.executable)
    finally:
        pool.shutdown()
