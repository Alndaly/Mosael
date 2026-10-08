"""测试要用的本机端口:每个测试进程独占一段,和同一台机器上别的测试进程(别的 worker、别的检出同时在跑的测试套)互不相交。

**为什么要独占。** 起服务的测试大多是「先挑一个此刻空着的端口,过一会儿才让服务去绑」—— 中间隔着装、试起这些步骤。
此前每个 xdist worker 按编号一段(gw2 是 20400 起),段内起点再随机挪一点:同一套测试里互不相干,可几个检出同时跑全套时,
两边的 gw2 落在同一段,各自挑「第一个空着的」,挑中的往往是同一个。后挑的那边过一会儿去绑,端口已经被先起的服务占了:
`test_装要确认_建成让Mosael装_试起通过才记成装好` 在满载的全套里红过一次,「端口 20413 被别的程序占着」。

现在每个测试进程起来时,在临时目录里给一段端口拿一把文件锁(`flock`,非阻塞):拿到的那一段这个进程用到结束,别的进程跳过
它去拿下一段。进程怎么结束(包括 kill -9)锁都随之放掉。优先拿和 worker 编号对应的那一段,一般不用往后找。

不用「绑 0 拿一个再放掉」:macOS 的临时端口是全系统**顺着往上发**的,放掉的那个之后,别的进程紧接着拿到的就是它附近的几个。
各段落在 20000–32000,不在系统发临时端口的范围里(macOS 49152 起、Linux 32768 起)。

这个模块不 import app:要在子进程里单独用(回归测试里模拟「另一个测试进程」)。
"""

from __future__ import annotations

import os
import socket
import sys
import tempfile
from pathlib import Path

#: 一段多少个端口。前一半留给「被测的产品自己往上找」(`first_free_port_of_this_worker` 给的起点),后一半给测试自己起的替身。
BLOCK_SIZE = 200
FIRST_PORT = 20000
BLOCKS = 60  # 20000–31999
#: 锁放在哪。回归测试给子进程指一个自己的目录,不和同时在跑的别的测试套抢同一批锁。
LOCK_DIR = Path(os.environ.get("MOSAEL_TEST_PORT_LOCKS") or Path(tempfile.gettempdir()) / "mosael-test-port-blocks")

_held: dict[str, object] = {}


def _worker_index() -> int:
    worker = os.environ.get("PYTEST_XDIST_WORKER", "")
    return int(worker[2:]) if worker.startswith("gw") and worker[2:].isdigit() else 0


def _lock(path: Path):
    """拿到这把锁就交回开着的文件(锁跟着它走,进程结束才放);别人拿着就交回 None。"""
    handle = path.open("a+")
    if sys.platform == "win32":  # pragma: no cover — CI 和开发机都不是 Windows;那边照编号分段,不加锁
        return handle
    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        return None
    return handle


def block() -> range:
    """这个进程独占的那一段端口。第一次调用时拿锁,之后一直是它。"""
    held = _held.get("block")
    if isinstance(held, range):
        return held
    LOCK_DIR.mkdir(parents=True, exist_ok=True)
    preferred = _worker_index() % BLOCKS
    for offset in range(BLOCKS):
        index = (preferred + offset) % BLOCKS
        start = FIRST_PORT + index * BLOCK_SIZE
        handle = _lock(LOCK_DIR / f"{start}.lock")
        if handle is None:
            continue
        _held["handle"] = handle
        _held["block"] = range(start, start + BLOCK_SIZE)
        return _held["block"]  # type: ignore[return-value]
    raise RuntimeError(f"{BLOCKS} 段端口都被别的测试进程占着(锁在 {LOCK_DIR})")


def listening(port: int) -> bool:
    """这个端口现在有没有人在听(和 local_services.supervisor.port_in_use 同一个判法:带 SO_REUSEADDR 试绑)。"""
    for host in ("127.0.0.1", "0.0.0.0"):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            if sys.platform != "win32":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
            except OSError:
                return True
    return False


def first_free_for_the_product() -> int:
    """给被测的产品当「从哪往上找」的起点:本进程那一段前一半里,第一个这时没人在听的。"""
    ours = block()
    for port in ours[: BLOCK_SIZE // 2]:
        if not listening(port):
            return port
    raise RuntimeError(f"{ours.start}..{ours.start + BLOCK_SIZE // 2 - 1} 全有人在听")


def free_port() -> int:
    """给测试自己起的替身、或要一个「没人在听的端口」:本进程那一段后一半里轮着给,连着要几次拿到的都不一样。"""
    ours = block()
    spare = ours[BLOCK_SIZE // 2 :]
    cursor = int(_held.get("cursor", 0))  # type: ignore[arg-type]
    for step in range(len(spare)):
        port = spare[(cursor + step) % len(spare)]
        if not listening(port):
            _held["cursor"] = (cursor + step + 1) % len(spare)
            return port
    raise RuntimeError(f"{spare.start}..{spare.stop - 1} 全有人在听")


if __name__ == "__main__":  # 回归测试里当「另一个测试进程」用:拿一段,报出起点,拿着锁等到被告知结束
    print(block().start, flush=True)
    sys.stdin.readline()
