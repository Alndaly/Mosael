"""管道坏了的 worker 要被踢出池子,而不是永远留着且永远 busy。

## 现场

`_request_locked` 先 `busy = True`,再 `stdin.write(...)`。而 `stdin.write` 在子进程已经关掉
stdin 时抛的是 `BrokenPipeError`(`OSError` 的子类),**不是 `RuntimeError`** —— 而
`WorkerPool.request` 原先只捕 `RuntimeError`。于是三件事一起发生:

1. worker 留在 `self._workers` 里;
2. `busy` 永远是 `True`(归位散在 `_read_until_done` 的几条出口上,一条都没走到),
   而 `_reap_once` 明确跳过 busy 的 —— **闲置回收永远不会碰它**;
3. 进程本体还活着的话(只是管道坏了),`_ensure` 会把同一个坏 worker 一直发回去 ——
   每次请求都 `BrokenPipeError`,十几 GB 显存也一直挂着。

**为什么看不出来**:子进程整个死掉是常见情况,而那一路是对的(`alive` 为 False → 换一个新的)。
"进程活着但管道坏了"少见得多,它的表现是"配音这功能一直报一句看不懂的错、重启才好" ——
指向不了进程池。

判据因此是**"请求失败了就假定这个 worker 不可信"**,而不是"失败的类型对不对得上"。
"""

from __future__ import annotations

import sys
import textwrap

import pytest

from app.ai.runtime import tts_daemon


def _closes_stdin_then_lives(tmp_path) -> str:
    """读一行就把 stdin 关掉,然后一直活着 —— 正是"进程还在、管道坏了"那个形状。"""
    script = tmp_path / "deaf_worker.py"
    script.write_text(
        textwrap.dedent(
            """
            import sys, time
            sys.stdin.readline()
            sys.stdin.close()
            time.sleep(300)
            """
        ),
        encoding="utf-8",
    )
    return str(script)


def test_管道坏了的worker不会永远留在池子里(tmp_path) -> None:
    pool = tts_daemon.WorkerPool(worker_path=_closes_stdin_then_lives(tmp_path), idle_seconds=60)
    try:
        # 第一次:worker 读走这一行就把 stdin 关了,自己不回话 —— 这一次按超时失败。
        # **失败的类型不是这条测试关心的**(那正是被修的那个毛病:池子原先按类型判该不该
        # 踢人,而判据应该是"请求失败了就假定这个 worker 不可信")。所以这里只要求它失败。
        with pytest.raises(Exception):  # noqa: B017 —— 类型无关正是本条的要点
            pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"}, timeout=1.5)

        # **关键**:失败之后它不该还在池子里。原先留着,而且 busy 永远为真。
        assert not pool.alive("fish-speech", sys.executable), (
            "坏掉的 worker 还在池子里 —— 下一次请求会再拿到同一个,而闲置回收跳过 busy 的,"
            "它会一直占着显存"
        )
    finally:
        pool.shutdown()


def test_busy只有一个归位处(tmp_path) -> None:
    """`stdin.write` 抛异常时也要归位 —— 那几条散落的出口一条都走不到。"""
    from app.ai.runtime.worker_pool import ResidentWorker

    source = ResidentWorker._request_locked.__doc__ or ""
    import inspect

    body = inspect.getsource(ResidentWorker._request_locked)
    assert body.count("self.busy = False") == 1, "busy 的归位又散开了"
    assert "finally:" in body, "归位不在 finally 里 —— 抛异常那条路上就丢了"
    assert source is not None


def test_等不到管道会说出来_而不是无声等满超时(tmp_path) -> None:
    """同一个 worker 一次只跑一个请求。第二个调用方原先会挂到前一个的 timeout(默认 1800 秒),
    期间不检查取消 —— 用户那一侧是"点了没反应"。"""
    import threading

    from app.ai.runtime.worker_pool import ResidentWorker

    slow = tmp_path / "slow.py"
    slow.write_text(
        textwrap.dedent(
            """
            import json, sys, time
            for line in sys.stdin:
                if not line.strip():
                    continue
                time.sleep(3)
            """
        ),
        encoding="utf-8",
    )
    pool = tts_daemon.WorkerPool(worker_path=str(slow), idle_seconds=60)
    try:
        def _hold() -> None:
            # 这一个注定超时失败 —— 它的职责只是**占住管道**,失败本身不是这条测试关心的。
            try:
                pool.request("fish-speech", sys.executable, {"a": 1}, timeout=2.5)
            except Exception:  # noqa: BLE001
                pass

        held = threading.Thread(target=_hold, daemon=True)
        held.start()
        import time as _t

        _t.sleep(0.4)  # 让第一个先拿到管道
        with pytest.raises(RuntimeError, match="正忙"):
            pool.request("fish-speech", sys.executable, {"a": 2}, timeout=0.3)
        held.join(timeout=10)
    finally:
        pool.shutdown()
    assert ResidentWorker is not None
