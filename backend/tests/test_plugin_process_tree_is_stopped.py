"""超时、取消停下的是插件的**整棵进程树**,不只是它的入口脚本。

插件的入口往往只是个调度:Remotion 起 `node render.mjs`,Manim 起 manim 再起 ffmpeg。此前超时和取消
只杀入口那一个进程 ——

· 孙进程照跑:用户点了停止,渲染还在后台吃满 CPU,直到它自己跑完;
· 它继承着插件的 stdout:任务里取消时 `communicate()` 要等管道关上才返回,流式调用读 stdout 的那个
  线程等不到 EOF —— 调用卡住,直到孙进程自己退出。
"""

from __future__ import annotations

import os
import signal
import textwrap
import threading
import time
from pathlib import Path

import pytest

from app.domain.plugins import runtime
from app.domain.plugins.runtime import PluginCancelled, PluginTimeout, StreamHooks, execute_tool, stream_tool

pytestmark = pytest.mark.skipif(os.name == "nt", reason="用 POSIX 的 pid 探活")

#: 入口脚本:起一个继承 stdout 的孙进程,把它的 pid 记下来,然后自己也不退。
ENTRY = textwrap.dedent(
    """
    import os, subprocess, sys, time
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    with open(os.environ["PID_FILE"], "w") as handle:
        handle.write(str(child.pid))
    time.sleep(60)
    """
)


@pytest.fixture
def plugin(tmp_path: Path):
    plugin_dir = tmp_path / "p"
    plugin_dir.mkdir()
    (plugin_dir / "main.py").write_text(ENTRY, encoding="utf-8")
    pid_file = tmp_path / "grandchild.pid"
    yield plugin_dir, pid_file
    if pid_file.is_file():
        try:
            os.kill(int(pid_file.read_text()), signal.SIGKILL)
        except (ProcessLookupError, ValueError):
            pass


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _grandchild_gone(pid_file: Path, within: float = 5.0) -> bool:
    deadline = time.monotonic() + within
    while not pid_file.is_file() and time.monotonic() < deadline:
        time.sleep(0.05)
    pid = int(pid_file.read_text())
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not _alive(pid)


def _wait_for(pid_file: Path) -> None:
    deadline = time.monotonic() + 10
    while not pid_file.is_file() and time.monotonic() < deadline:
        time.sleep(0.05)


def test_超时连孙进程一起停(plugin) -> None:
    plugin_dir, pid_file = plugin
    with pytest.raises(PluginTimeout):
        execute_tool(plugin_dir, "main.py", "x", {}, credentials={"PID_FILE": str(pid_file)}, timeout=2)
    assert _grandchild_gone(pid_file), "插件超时之后,它起的孙进程还在跑"


def test_任务里取消立刻返回_孙进程也停(plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    """取消任务拉下挂在任务名下的开关。此前开关只杀入口进程,而孙进程攥着 stdout,
    `communicate()` 一直等到孙进程自己跑完(这里是 60 秒)才返回。"""
    plugin_dir, pid_file = plugin
    switches: list = []
    monkeypatch.setattr(runtime, "current_parent_job_id", lambda: "job-1")
    monkeypatch.setattr(runtime, "register_job_child", lambda _job, switch: switches.append(switch))
    monkeypatch.setattr(runtime, "detach_job_child", lambda _job, _switch: None)

    def cancel_soon() -> None:
        _wait_for(pid_file)
        switches[0].kill()

    threading.Thread(target=cancel_soon, daemon=True).start()
    started = time.monotonic()
    with pytest.raises(PluginCancelled):
        execute_tool(plugin_dir, "main.py", "x", {}, credentials={"PID_FILE": str(pid_file)}, timeout=50)
    assert time.monotonic() - started < 20, "取消之后还在等孙进程关上 stdout"
    assert _grandchild_gone(pid_file)


def test_流式调用超时不会卡在读_stdout_上(plugin, monkeypatch: pytest.MonkeyPatch) -> None:
    """没给暂存目录(没有取消文件可建)时超时直接杀。此前只杀入口进程,孙进程攥着 stdout,
    读 stdout 的线程等不到 EOF,整个调用卡到孙进程自己退出为止。"""
    plugin_dir, pid_file = plugin
    hooks = StreamHooks(on_progress=lambda *_: None, on_task=lambda _t: None, is_cancelled=lambda: False)
    outcome: list = []

    def run() -> None:
        try:
            stream_tool(plugin_dir, "main.py", "x", {}, {"PID_FILE": str(pid_file)}, hooks=hooks, timeout=2)
        except BaseException as exc:  # noqa: BLE001 — 记下来给主线程断言
            outcome.append(exc)

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=25)
    assert not worker.is_alive(), "流式调用超时后卡住了"
    assert outcome and isinstance(outcome[0], PluginTimeout)
    assert _grandchild_gone(pid_file)
