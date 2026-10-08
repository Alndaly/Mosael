import subprocess
import sys

import pytest
from app.core.child_process import ProcessOutputLimitExceeded, run_bounded


@pytest.mark.parametrize("fd", [1, 2])
def test_unterminated_output_is_bounded_while_the_child_is_running(fd):
    # 子进程一直写、永不自己结束:能让它停下的只有输出上限 —— 要是上限等子进程退出才看,先到的就是 30 秒的超时,
    # pytest.raises 拿到的是 TimeoutExpired,这条就红。此前子进程写一秒就退,再量「< 1 秒」,里面还包着起一个 Python。
    with pytest.raises(ProcessOutputLimitExceeded):
        run_bounded([sys.executable, "-c", f"import os,time\nwhile True:\n os.write({fd},b'x'*4096)\n time.sleep(.01)"], timeout=30, max_output_bytes=8192, what="test")


def test_deadline_applies_when_child_never_reads_stdin():
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded([sys.executable, "-c", "import time;time.sleep(10)"], input=b"x"*1_000_000, timeout=.2, max_output_bytes=100, what="test")


def test_binary_output_and_diagnostics_survive_under_budget():
    out = run_bounded([sys.executable, "-c", "import os;os.write(1,b'\\xff');os.write(2,b'err')"], timeout=2, max_output_bytes=4, what="test")
    assert out.returncode == 0 and out.stdout == b"\xff" and out.stderr == b"err"
