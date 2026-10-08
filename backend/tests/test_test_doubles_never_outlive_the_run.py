"""测试起的替身进程不比测试进程活得久 —— 测试进程被强杀也一样。

现场:维护者机器上挂着八个 `fake_local_service.py`,父进程是 1 号,所在的 worktree 两天前就删了。看护起本机服务时给的是
新会话、日志写进文件:测试进程一被 kill -9(超时掐掉、手动停掉),它们收不到信号、也读不到管道断开,假服务又是
`serve_forever`,就一直挂着。复现:跑着本机服务的测试时 kill -9 掉 pytest,假服务留了下来。

两层兜底:
- 一直不退的替身自己跟着起它的测试进程走(tests/fake_local_service.py 的 `_follow_owner`,孙进程也是)—— 强杀时
  测试进程里什么都跑不了,只能靠它们自己;
- 会话收尾时,还在跑的子进程连同它们的进程组一起收掉(tests/child_processes.py,conftest 接上)—— 兜半路失败、忘了收、
  Ctrl-C 打断的那些。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest

from tests import child_processes
from tests.util import until

pytestmark = pytest.mark.skipif(os.name != "posix", reason="按 pid 探活、按进程组收,用的是 POSIX 的那一套")

FAKE = Path(__file__).resolve().parent / "fake_local_service.py"

#: 「测试进程」的替身:像看护那样在新会话里起假服务(带一个孙进程),把两个 pid 报出来,然后一直等着被杀。
OWNER = """
import subprocess, sys, time
from pathlib import Path
fake, child_file, log = sys.argv[1], Path(sys.argv[2]), sys.argv[3]
service = subprocess.Popen([sys.executable, fake, "--port", "0", "--child", str(child_file)],
                           start_new_session=True, stdout=open(log, "w"), stderr=subprocess.STDOUT)
while not child_file.is_file() or not child_file.read_text():
    time.sleep(0.05)
print(service.pid, child_file.read_text(), flush=True)
time.sleep(600)
"""


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _kill(*pids: int) -> None:
    for pid in pids:
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def test_起假服务的进程被强杀_假服务和它的孙进程自己退出(tmp_path: Path) -> None:
    owner = subprocess.Popen(
        [sys.executable, "-c", OWNER, str(FAKE), str(tmp_path / "child.pid"), str(tmp_path / "service.log")],
        stdout=subprocess.PIPE, text=True,
    )
    service, grandchild = (int(pid) for pid in owner.stdout.readline().split())
    try:
        assert _alive(service) and _alive(grandchild)
        owner.kill()  # 测试进程被 kill -9:它自己什么收尾都做不了
        owner.wait(timeout=30)
        assert until(lambda: not _alive(service)), "起它的进程没了,假服务还挂着"
        assert until(lambda: not _alive(grandchild)), "起它的进程没了,假服务的孙进程还挂着"
    finally:
        _kill(service, grandchild)
        owner.stdout.close()


def test_会话收尾时还在跑的子进程_连同孙进程一起收掉() -> None:
    leader = subprocess.Popen(
        [sys.executable, "-c", (
            "import subprocess, sys, time\n"
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(600)'])\n"
            "print(child.pid, flush=True)\n"
            "time.sleep(600)\n"
        )],
        start_new_session=True, stdout=subprocess.PIPE, text=True,
    )
    grandchild = int(leader.stdout.readline())
    try:
        assert leader.pid in child_processes.spawned(), "经 subprocess.Popen 起的子进程没被记下来"
        assert child_processes.sweep([leader.pid]) == [leader.pid]
        assert not _alive(leader.pid)
        assert until(lambda: not _alive(grandchild)), "收的是它一个,不是它那一整组:孙进程还在"
        assert child_processes.sweep([leader.pid]) == [], "收过的不再碰(号可能已经给了别人)"
    finally:
        _kill(leader.pid, grandchild)
        leader.stdout.close()
