"""worker 卡住不说话时,请求必须超时 —— 而不是永远等下去。

`_Worker.request` 的注释写着「最坏的失败是没有回音 —— 那看起来和还在跑一模一样,所以必须
变成一个明确的错误」。而代码没有兑现它:

    deadline = time.monotonic() + timeout
    for line in self.process.stdout:      # ← **阻塞**在 readline 上
        ...
        if time.monotonic() > deadline:   # ← 只有"收到一行未知事件"时才走到这儿
            break

进程**退出**时 stdout 关闭,循环结束,这条路是通的(已有测试)。但进程**活着却不说话**时
(卡在一次下载、卡在 torch 的某个锁上),readline 永远不返回:

  - 任务永远不失败,界面上一直是"运行中";
  - `busy` 永远为真,闲置回收不敢动它;
  - TTS_SLOTS 那个名额被一直占着 —— **之后所有配音永久排队**。

一个写在注释里但没有兑现的判断,是这一整天反复出现的形状。这条测试让它兑现。
"""

from __future__ import annotations

import sys
import textwrap
import time

import pytest

from app.ai.runtime import tts_daemon


def _mute_worker(tmp_path) -> str:
    """收了请求就装死:不回话,也不退出。"""
    script = tmp_path / "mute_worker.py"
    script.write_text(
        textwrap.dedent(
            """
            import sys, time
            for line in sys.stdin:
                if line.strip():
                    time.sleep(600)
            """
        ),
        encoding="utf-8",
    )
    return str(script)


def test_a_silent_worker_raises_instead_of_hanging(tmp_path) -> None:
    pool = tts_daemon.WorkerPool(worker_path=_mute_worker(tmp_path))
    began = time.monotonic()
    try:
        with pytest.raises(RuntimeError):
            pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"}, timeout=2)
    finally:
        pool.shutdown()

    elapsed = time.monotonic() - began
    assert elapsed < 15, f"等了 {elapsed:.0f} 秒还没放弃 —— 超时没有兑现"


def test_the_slot_is_released_after_a_timeout(tmp_path) -> None:
    """超时之后那个进程不能还占着 busy —— 否则回收线程永远不敢动它,内存也回不来。"""
    pool = tts_daemon.WorkerPool(worker_path=_mute_worker(tmp_path))
    try:
        with pytest.raises(RuntimeError):
            pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"}, timeout=2)
        assert not pool.alive("fish-speech", sys.executable), "卡住的进程该被杀掉,而不是留着"
    finally:
        pool.shutdown()


def test_a_later_request_still_works(tmp_path) -> None:
    """一次超时不该把这条路堵死 —— 下一次合成要能起一个新进程。"""
    import json

    good = tmp_path / "good.py"
    good.write_text(
        textwrap.dedent(
            f"""
            import json, sys
            for line in sys.stdin:
                if not line.strip():
                    continue
                sys.stdout.write({tts_daemon.EVENT_PREFIX!r} + json.dumps({{"event": "done", "ok": True}}) + "\\n")
                sys.stdout.flush()
            """
        ),
        encoding="utf-8",
    )
    pool = tts_daemon.WorkerPool(worker_path=_mute_worker(tmp_path))
    try:
        with pytest.raises(RuntimeError):
            pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"}, timeout=2)
        pool._worker_path = str(good)  # 换成一个正常的 worker,模拟"下一次"
        assert pool.request("fish-speech", sys.executable, {"output_path": "/tmp/b.wav"}, timeout=20)["ok"]
    finally:
        pool.shutdown()
