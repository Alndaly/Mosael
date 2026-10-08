"""测试挑的端口不和同一台机器上别的测试进程撞(tests/ports.py)。

现场:`test_装要确认_建成让Mosael装_试起通过才记成装好` 在满载的全套里(gw2)红过一次 —— 「端口 20413 被别的程序占着」。
挑端口和服务去绑之间隔着装、试起;此前每个 worker 按编号分段,段内起点随机挪一点,同一台机器上另一套测试的 gw2 落在同一段、
挑「第一个空着的」,挑中的是同一个,先起的那边把它占了。

这里不靠两套测试恰好同时跑:另起几个进程当「几套测试的同一个 worker」(同样的 PYTEST_XDIST_WORKER),让它们各自去拿一段 ——
拿到的必须两两不相交。锁放在这条测试自己的临时目录里,不和机器上同时在跑的别的测试套抢,结果不看别人。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests import ports

BACKEND = Path(__file__).resolve().parents[1]

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Windows 上没有 flock,照编号分段")


def _a_test_process(locks: Path) -> tuple[subprocess.Popen, int]:
    """一个测试进程(都是 gw2):拿一段端口,报出起点,一直拿着,直到关它的标准输入。"""
    process = subprocess.Popen(
        [sys.executable, "-m", "tests.ports"], cwd=BACKEND, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        env={**os.environ, "PYTEST_XDIST_WORKER": "gw2", "MOSAEL_TEST_PORT_LOCKS": str(locks)},
    )
    return process, int(process.stdout.readline())


def _done(*processes: subprocess.Popen) -> None:
    for process in processes:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        process.wait(timeout=30)
        process.stdout.close()


def test_三套测试的同一个worker_拿到的三段端口两两不相交(tmp_path: Path) -> None:
    started = [_a_test_process(tmp_path) for _ in range(3)]
    try:
        starts = [start for _, start in started]
        assert len(set(starts)) == 3, f"三个 gw2 拿到的段起点是 {starts} —— 有重的,就会挑到同一个端口"
        assert starts[0] == ports.FIRST_PORT + 2 * ports.BLOCK_SIZE, "没人抢的时候,拿的就是自己编号那一段"
    finally:
        _done(*(process for process, _ in started))


def test_拿着那一段的进程没了_锁就放了(tmp_path: Path) -> None:
    """进程怎么结束(kill -9 也一样)锁都放掉:段不会越用越少。"""
    gone, start = _a_test_process(tmp_path)
    gone.kill()
    _done(gone)
    again, start_again = _a_test_process(tmp_path)
    try:
        assert start_again == start, "前一个进程没了,它那一段该能被下一个拿到"
    finally:
        _done(again)


def test_本进程要的端口_都在自己那一段里_替身的连着要也不重() -> None:
    ours = ports.block()
    for_the_product = ports.first_free_for_the_product()
    doubles = [ports.free_port() for _ in range(5)]
    assert for_the_product in ours[: ports.BLOCK_SIZE // 2], "产品往上找的起点在前一半"
    assert all(port in ours[ports.BLOCK_SIZE // 2 :] for port in doubles), "替身的在后一半,和产品往上找的不碰"
    assert len(set(doubles)) == len(doubles), "连着要几次拿到的该各不相同(两个替身不抢一个端口)"
