import subprocess
import sys
import time

import pytest
from app.core.child_process import ProcessOutputLimitExceeded, run_bounded


@pytest.mark.parametrize("fd", [1, 2])
def test_unterminated_output_is_bounded_while_the_child_is_running(fd):
    started = time.monotonic()
    with pytest.raises(ProcessOutputLimitExceeded):
        run_bounded([sys.executable, "-c", f"import os,time\nfor i in range(100):\n os.write({fd},b'x'*4096)\n time.sleep(.01)"], timeout=2, max_output_bytes=8192, what="test")
    assert time.monotonic() - started < 1


def test_deadline_applies_when_child_never_reads_stdin():
    with pytest.raises(subprocess.TimeoutExpired):
        run_bounded([sys.executable, "-c", "import time;time.sleep(10)"], input=b"x"*1_000_000, timeout=.2, max_output_bytes=100, what="test")


def test_binary_output_and_diagnostics_survive_under_budget():
    out = run_bounded([sys.executable, "-c", "import os;os.write(1,b'\\xff');os.write(2,b'err')"], timeout=2, max_output_bytes=4, what="test")
    assert out.returncode == 0 and out.stdout == b"\xff" and out.stderr == b"err"
