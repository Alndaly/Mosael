"""合成 worker 常驻:18 GB 权重加载一次,不是每次合成加载一次。

实测这台机器上一次 Fish Speech 合成:

    模型加载 511.9s(8.5 分钟)   ← 每次合成都从头来一遍
    解码     2.37 it/s

用户看到的是「20% 卡了 14 分钟」。里头绝大部分时间在**重新加载同一个模型** —— 上一次合成
刚把它读进内存,进程一退,全扔了。

顺带解决另一半:那个 20% 是合成开始时写死的一个数,整个推理过程不再更新。它不代表进度,
它代表**没有进度上报**。常驻进程有了稳定的通道,worker 就能一路把"在做哪一步、到第几段"
报回来。

协议为什么带哨兵前缀:引擎自己会往 stdout / stderr 打 tqdm 进度条和 loguru 日志,通道里
本来就有噪声。约定一个前缀,宿主只认带前缀的行,其余原样当日志 —— 比"假设子进程只说我们
要的话"结实。
"""

from __future__ import annotations

import json
import sys
import textwrap
import time

import pytest

from app.ai.runtime import tts_daemon


def _fake_worker(tmp_path, body: str) -> str:
    """一个假 worker:按真协议收发,但不加载任何模型。"""
    script = tmp_path / "fake_worker.py"
    script.write_text(
        textwrap.dedent(
            f"""
            import json, sys
            PREFIX = {tts_daemon.EVENT_PREFIX!r}
            def emit(payload):
                sys.stdout.write(PREFIX + json.dumps(payload) + "\\n")
                sys.stdout.flush()
            loaded = 0
            for line in sys.stdin:
                line = line.strip()
                if not line:
                    continue
                request = json.loads(line)
{textwrap.indent(textwrap.dedent(body), " " * 16)}
            """
        ),
        encoding="utf-8",
    )
    return str(script)


ECHO = """
loaded += 1
print("噪声:模型加载中 47%|=====   |", flush=True)
emit({"event": "progress", "phase": "generate", "fraction": 0.5})
emit({"event": "done", "output": request["output_path"], "loads": loaded})
"""


def test_one_process_serves_many_requests(tmp_path) -> None:
    """第二次合成不该再加载一次 —— 这就是那 8.5 分钟省下来的地方。"""
    worker = _fake_worker(tmp_path, ECHO)
    pool = tts_daemon.WorkerPool(worker_path=worker)
    try:
        first = pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"})
        second = pool.request("fish-speech", sys.executable, {"output_path": "/tmp/b.wav"})
    finally:
        pool.shutdown()

    assert first["loads"] == 1
    assert second["loads"] == 2, "同一个进程该记得自己活过 —— 说明没有重启"


def test_progress_is_reported_while_it_works(tmp_path) -> None:
    seen: list[dict] = []
    worker = _fake_worker(tmp_path, ECHO)
    pool = tts_daemon.WorkerPool(worker_path=worker)
    try:
        pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"}, on_progress=seen.append)
    finally:
        pool.shutdown()

    assert seen and seen[0]["fraction"] == 0.5, seen


def test_engine_noise_does_not_break_the_protocol(tmp_path) -> None:
    """tqdm 和 loguru 会往同一个通道里写 —— 只认带前缀的行。"""
    worker = _fake_worker(tmp_path, ECHO)
    pool = tts_daemon.WorkerPool(worker_path=worker)
    try:
        result = pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"})
    finally:
        pool.shutdown()

    assert result["output"] == "/tmp/a.wav"


def test_a_dead_worker_is_restarted(tmp_path) -> None:
    """进程会死(OOM、被杀、崩)。下一次请求要能自己起来,而不是从此报错。"""
    worker = _fake_worker(tmp_path, ECHO)
    pool = tts_daemon.WorkerPool(worker_path=worker)
    try:
        pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"})
        pool.kill("fish-speech", sys.executable)
        again = pool.request("fish-speech", sys.executable, {"output_path": "/tmp/b.wav"})
    finally:
        pool.shutdown()

    assert again["loads"] == 1, "重启之后是一个新进程,计数该从头"


def test_a_worker_error_surfaces_as_an_exception(tmp_path) -> None:
    worker = _fake_worker(tmp_path, '''
emit({"event": "error", "message": "权重加载失败"})
''')
    pool = tts_daemon.WorkerPool(worker_path=worker)
    try:
        with pytest.raises(RuntimeError) as caught:
            pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"})
    finally:
        pool.shutdown()

    assert "权重加载失败" in str(caught.value)


def test_a_worker_that_dies_mid_request_does_not_hang(tmp_path) -> None:
    """最坏的失败是"没有回音" —— 那看起来和"还在跑"一模一样。"""
    worker = _fake_worker(tmp_path, "raise SystemExit(1)")
    pool = tts_daemon.WorkerPool(worker_path=worker)
    try:
        with pytest.raises(RuntimeError):
            pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"}, timeout=20)
    finally:
        pool.shutdown()


def test_different_engines_get_different_processes(tmp_path) -> None:
    """两个引擎各自常驻 —— 一个进程里同时挂两套权重是 30 GB。"""
    worker = _fake_worker(tmp_path, ECHO)
    pool = tts_daemon.WorkerPool(worker_path=worker)
    try:
        pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"})
        other = pool.request("f5-tts", sys.executable, {"output_path": "/tmp/b.wav"})
    finally:
        pool.shutdown()

    assert other["loads"] == 1, "另一个引擎该是另一个进程"


def test_an_idle_worker_is_released(tmp_path) -> None:
    """18 GB 常驻是**借**用户的内存。闲下来要还回去,而不是占到应用退出。"""
    worker = _fake_worker(tmp_path, ECHO)
    pool = tts_daemon.WorkerPool(worker_path=worker, idle_seconds=0.4)
    try:
        pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"})
        assert pool.alive("fish-speech", sys.executable)
        deadline = time.time() + 5
        while pool.alive("fish-speech", sys.executable) and time.time() < deadline:
            time.sleep(0.1)
        assert not pool.alive("fish-speech", sys.executable), "闲了很久还占着 18 GB"
    finally:
        pool.shutdown()


def test_dropping_workers_leaves_the_pool_usable(tmp_path) -> None:
    """设置页每保存一次就要放掉旧进程(它抱着旧 env)。**放掉 ≠ 关掉池子** ——
    用 shutdown() 会把回收线程一起停掉,池子从此不再回收闲置进程,而它看起来还能用。
    """
    worker = _fake_worker(tmp_path, ECHO)
    pool = tts_daemon.WorkerPool(worker_path=worker)
    try:
        pool.request("fish-speech", sys.executable, {"output_path": "/tmp/a.wav"})
        pool.drop_all()
        assert not pool.alive("fish-speech", sys.executable)

        again = pool.request("fish-speech", sys.executable, {"output_path": "/tmp/b.wav"})
        assert again["loads"] == 1, "放掉之后该起一个新的"
        assert not pool._stop.is_set(), "回收线程被停了 —— 闲置的 18 GB 再也不会还回去"
    finally:
        pool.shutdown()
