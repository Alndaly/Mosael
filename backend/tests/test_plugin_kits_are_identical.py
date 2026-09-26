"""进程插件的共用底子(`plugins/examples/*/tools/plugin_kit.py`)。

插件是各自打包、各自安装的,互相 import 不到,所以每个要用它的插件带一份**字节相同**的拷贝
(和对象存储插件共用 storage.py 同一个办法,见 test_storage_plugins_share_one_core)。这里钉两件事:

- 几份拷贝一个字节都不差 —— 改一处就得处处一起改;
- 它说到的那几件难事真的做到了:停要连子孙一起停(组长先退了也一样)、`\\r` 重画的进度条逐次读得到、
  取消和时限在读输出的同一个循环里看、跨进程的锁真的互斥。
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).resolve().parents[2] / "plugins" / "examples"
COPIES = sorted(EXAMPLES.glob("*/tools/plugin_kit.py"))
posix_only = pytest.mark.skipif(sys.platform == "win32", reason="用 os.kill(pid, 0) 看进程还在不在")


def test_每份拷贝字节相同() -> None:
    assert {path.parent.parent.name for path in COPIES} >= {"manim", "remotion"}
    assert len({path.read_bytes() for path in COPIES}) == 1, [str(path) for path in COPIES]


@pytest.fixture(params=COPIES, ids=lambda path: path.parent.parent.name)
def kit(request):
    spec = importlib.util.spec_from_file_location(f"plugin_kit_{request.param.parent.parent.name}", request.param)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass 要在 sys.modules 里找到自己的模块
    spec.loader.exec_module(module)
    return module


def _script(tmp_path: Path, body: str) -> list[str]:
    path = tmp_path / "child.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return [sys.executable, str(path)]


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_进度条按回车切开_两个流都读到(kit, tmp_path) -> None:
    seen: list[tuple[str, str]] = []
    args = _script(tmp_path, """
        import sys
        sys.stderr.write("bar 10%\\rbar 20%\\rbar 30%\\n"); sys.stderr.flush()
        print("done")
    """)
    finished = kit.follow(args, locale="zh", timeout=30, on_line=lambda stream, text: seen.append((stream, text)))
    assert finished.returncode == 0
    assert [text for stream, text in seen if stream == "err"] == ["bar 10%", "bar 20%", "bar 30%"]
    assert ("out", "done") in seen and list(finished.tail)[-1] in ("done", "bar 30%")


def test_大段stdin不会和输出互相等死(kit, tmp_path) -> None:
    args = _script(tmp_path, """
        import sys
        sys.stdout.write("x" * 300_000 + "\\n"); sys.stdout.flush()
        print(len(sys.stdin.read()))
    """)
    lines: list[str] = []
    kit.follow(args, locale="zh", timeout=30, stdin_text="中" * 200_000, on_line=lambda _s, text: lines.append(text))
    assert lines[-1] == "200000"


@posix_only
def test_取消时连子孙一起停_组长先退了也一样(kit, tmp_path, monkeypatch) -> None:
    """npm 退了、它起的 node 还在;Manim 退了、LaTeX 还在 —— 只看组长会把它们漏掉。"""
    cancel = tmp_path / "cancel"
    monkeypatch.setenv("MOSAEL_PLUGIN_CANCEL_FILE", str(cancel))
    pid_file = tmp_path / "grandchild.pid"
    args = _script(tmp_path, f"""
        import subprocess, sys
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        open({str(pid_file)!r}, "w").write(str(child.pid))
        print("started", flush=True)
    """)

    def on_line(_stream: str, text: str) -> None:
        if text == "started":
            cancel.touch()

    with pytest.raises(kit.Cancelled):
        kit.follow(args, locale="zh", timeout=30, on_line=on_line)
    grandchild = int(pid_file.read_text())
    for _ in range(50):
        if not _alive(grandchild):
            break
        time.sleep(0.1)
    assert not _alive(grandchild), "孙进程成了孤儿,还在跑"


@posix_only
def test_到时限就停_抛TimedOut(kit, tmp_path) -> None:
    pid_file = tmp_path / "pid"
    args = _script(tmp_path, f"""
        import os, time
        open({str(pid_file)!r}, "w").write(str(os.getpid()))
        time.sleep(60)
    """)
    started = time.monotonic()
    with pytest.raises(kit.TimedOut):
        kit.follow(args, locale="en", timeout=1)
    assert time.monotonic() - started < 10
    assert not _alive(int(pid_file.read_text()))


def test_回调抛错也先停下子进程(kit, tmp_path) -> None:
    args = _script(tmp_path, """
        import time
        print("hello", flush=True)
        time.sleep(60)
    """)

    def explode(_stream: str, _text: str) -> None:
        raise RuntimeError("boom")

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="boom"):
        kit.follow(args, locale="zh", timeout=30, on_line=explode)
    assert time.monotonic() - started < 15


def test_跨进程的锁真的互斥(kit, tmp_path) -> None:
    lock = tmp_path / "setup.lock"
    holder = subprocess.Popen([sys.executable, "-c", textwrap.dedent(f"""
        import importlib.util, sys, time
        spec = importlib.util.spec_from_file_location("kit", {str(Path(kit.__file__))!r})
        kit = importlib.util.module_from_spec(spec); sys.modules["kit"] = kit; spec.loader.exec_module(kit)
        from pathlib import Path
        with kit.exclusive(Path({str(lock)!r}), locale="zh", timeout=10):
            print("held", flush=True)
            time.sleep(1.5)
    """)], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout is not None and holder.stdout.readline().strip() == "held"
        with pytest.raises(kit.TimedOut):
            with kit.exclusive(lock, locale="zh", timeout=0.3):
                pass
        started = time.monotonic()
        with kit.exclusive(lock, locale="zh", timeout=10):
            waited = time.monotonic() - started
        assert waited > 0.5, "拿锁的那个还没放,这边不该进得来"
    finally:
        holder.wait(timeout=10)


def test_文件名只留安全的字符_去掉调用方要加的扩展名(kit) -> None:
    assert kit.safe_stem("../../etc/课程 1.mp4", "x", ("mp4",)) == "etc_课程_1"
    assert kit.safe_stem("", "fallback") == "fallback"
    assert kit.safe_stem("clip.MOV", "x", ("mp4", "mov")) == "clip"
