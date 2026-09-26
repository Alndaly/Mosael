"""进程插件的共用底子:说人话、报进度、看取消、跑一个会说很多话的子进程、一把跨进程的锁。

**Manim 和 Remotion 各带一份字节相同的拷贝**(`tools/plugin_kit.py`)—— 插件是各自打包、各自安装的,
互相 import 不到;由 backend/tests/test_plugin_kits_are_identical.py 钉住,改一处就得两处一起改。
只用标准库。

## 为什么要有它

两个插件都要在本机起一串子进程(pip / Manim / LaTeX,npm / Node / Chrome),而这件事有三处容易错,
此前两个插件各错了一部分:

- **停要连子孙一起停**。宿主取消或超时时,只杀直接起的那个进程,它起的 LaTeX、Chrome 会成为孤儿接着跑、
  占着 CPU 写一个已经没人要的文件。所以子进程单独成组,停的时候整组停(`stop`)。
- **进度条用 `\\r` 原地重画**,按行读会一直读不到换行,于是边跑边报进度成了跑完才报。按块读,`\\r` 和
  `\\n` 都算分隔(`follow`)。
- **看取消、看时限要在读输出的同一个循环里**。读完再看就等于不看:一个卡住的子进程永远读不完。

同一台机器上可以同时有几次调用(宿主给插件的并发名额不止一个),两次「准备环境」同时删、同时装同一个目录
会装出一个半截的环境 —— 所以有 `exclusive`。
"""

from __future__ import annotations

import codecs
import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: 往宿主报一行(NDJSON):进度 `{"event": "progress", …}`,或者最后的结果 `{"ok": …}`。
Emit = Callable[[dict[str, Any]], None]


class PluginError(RuntimeError):
    """说得出口的失败,原样进工具结果。"""


class Cancelled(PluginError):
    """宿主建了取消文件:用户停了这次调用,或者宿主那边的预算用完了。"""


class TimedOut(PluginError):
    """插件自己给的时限到了。调用方按自己的活说一句能照着做的话(降画质、拆几段、填镜像)。"""

    def __init__(self, seconds: float) -> None:
        super().__init__(f"timed out after {seconds:g}s")
        self.seconds = seconds


def is_zh(locale: str) -> bool:
    return str(locale or "").replace("_", "-").split("-")[0].lower() == "zh"


def line(locale: str, zh: str, en: str) -> str:
    """一句给人看的话,按读的人用的语言(`zh-CN` 和 `zh` 是同一件事)。"""
    return zh if is_zh(locale) else en


# ---------------------------------------------------------------- 协议

def emit(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


_last_progress: list = [None]


def progress(send: Emit, fraction: float, message: str) -> None:
    """报一次进度。和上一次一模一样的不再报 —— 进度条一秒重画十几次,宿主要的是「变了」。"""
    event = {"event": "progress", "progress": round(max(0.0, min(1.0, fraction)), 4), "message": message[:200]}
    if event == _last_progress[0]:
        return
    _last_progress[0] = event
    send(event)


def cancel_requested() -> bool:
    """宿主建了取消文件没有(`MOSAEL_PLUGIN_CANCEL_FILE`)。不在任务里跑时没有这个变量,永远是 False。"""
    path = os.environ.get("MOSAEL_PLUGIN_CANCEL_FILE", "").strip()
    return bool(path) and Path(path).exists()


def data_dir(locale: str) -> Path:
    raw = os.environ.get("MOSAEL_PLUGIN_DATA_DIR", "").strip()
    if not raw:
        raise PluginError(line(
            locale,
            "宿主没有给插件持久目录(MOSAEL_PLUGIN_DATA_DIR)—— 请把 Mosael 升级到最新版。",
            "The host gave no persistent plugin directory (MOSAEL_PLUGIN_DATA_DIR). Please update Mosael.",
        ))
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def output_dir(locale: str) -> Path:
    raw = os.environ.get("MOSAEL_PLUGIN_OUTPUT_DIR", "").strip()
    if not raw:
        raise PluginError(line(locale, "宿主没有给产出目录(MOSAEL_PLUGIN_OUTPUT_DIR)。",
                               "The host gave no output directory (MOSAEL_PLUGIN_OUTPUT_DIR)."))
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_stem(value: Any, fallback: str, extensions: Sequence[str] = ()) -> str:
    """产出文件名:只留字母数字、中文、点、横线;去掉调用方要自己加的那几种扩展名。"""
    stem = re.sub(r"[^\w一-鿿.-]+", "_", str(value or "")).strip("._")[:80]
    for extension in extensions:
        if stem.lower().endswith("." + extension.lower()):
            stem = stem[: -len(extension) - 1]
            break
    return stem.strip("._") or fallback


def fresh_dir(parent: Path, *, max_age: float = 86400) -> Path:
    """这一次调用自己的工作目录,用完由调用方删。顺手清掉一天以前的残留(进程被强杀时来不及删)。"""
    parent.mkdir(parents=True, exist_ok=True)
    cutoff = time.time() - max_age
    for old in parent.iterdir():
        try:
            if old.is_dir() and old.stat().st_mtime < cutoff:
                shutil.rmtree(old, ignore_errors=True)
        except OSError:
            pass
    job = parent / uuid.uuid4().hex[:12]
    job.mkdir()
    return job


# ---------------------------------------------------------------- 从一堆输出里挑原因

_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_EXCEPTION_LINE = re.compile(r"\b\w*(Error|Exception)\b\s*:")
_PROGRESS_LINE = re.compile(r"\d+%\s*\||\|\s*\d+/\d+\s*\[|\d+(\.\d+)?\s*(it|file|[kMG]?i?[Bb])/s")
_NOISE_LINE = re.compile(
    r"^(?:[\^~]+|[-=_]{3,}|note:.*|hint:.*|File \".*\", line \d+.*|Traceback \(most recent call last\):"
    r"|During handling of the above exception.*|The above exception was the direct cause.*"
    r"|[│╭╰─╮╯┃━\s]+.*|Manim Community v[\d.]+)$",
    re.I,
)


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text or "")


def blame_line(output: str, fallback: str = "") -> str:
    """从子进程的输出里挑**说明失败原因**的那一行 —— 不是最后一行。

    和宿主的 core/text.blame_line 同一个判据(插件拿不到宿主的代码,所以抄一份):先从后往前找长得像
    异常的一行;找不到再找第一行不是噪声、不是进度条、也不是 rich 画的边框的。最后一行常常是一根
    进度条或一条分隔线,拿它当原因只会让人对着一句无关的话发愣。
    """
    lines = [one.strip() for one in strip_ansi(output).splitlines() if one.strip()]
    exception = next((one for one in reversed(lines) if _EXCEPTION_LINE.search(one)), None)
    if exception:
        return exception.strip("│ ")
    meaningful = next((one for one in reversed(lines) if not _NOISE_LINE.match(one) and not _PROGRESS_LINE.search(one)), None)
    return meaningful or fallback


# ---------------------------------------------------------------- 子进程

def group_kwargs() -> dict[str, Any]:
    """子进程单独成组:停的时候连它派生的进程(编译器、LaTeX、Chrome)一起停。"""
    if sys.platform == "win32":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def stop(process: subprocess.Popen) -> None:
    """停掉一个子进程**和它的子孙**。先礼后兵:先请它停,3 秒不停再杀。

    组长自己先退了也照样对整组发信号:npm 退出时它起的 node 还可能活着,只看组长会把它们漏掉。
    """
    try:
        if sys.platform == "win32":
            if process.poll() is None:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(process.pid)], capture_output=True, timeout=15)
        else:
            import signal

            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass  # 整组都已经没了
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


@dataclass
class Finished:
    """子进程跑完了(自己退的,不是被停的)。`tail` 是最后那些输出行,两个流按到达顺序混在一起。"""

    returncode: int
    tail: deque = field(default_factory=deque)


def _pump(stream, name: str, lines: "queue.Queue[tuple[str, str | None]]") -> None:
    # 进度条用 `\r` 原地重画,按行读会一直读不到换行 —— 所以按块读,`\r` 和 `\n` 都算分隔。
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buffer = ""
    try:
        while True:
            chunk = stream.read1(4096) if hasattr(stream, "read1") else stream.read(4096)
            if not chunk:
                break
            buffer += decoder.decode(chunk)
            parts = re.split(r"[\r\n]", buffer)
            buffer = parts.pop()
            for part in parts:
                if part.strip():
                    lines.put((name, part))
        buffer += decoder.decode(b"", final=True)
        if buffer.strip():
            lines.put((name, buffer))
    except (OSError, ValueError):
        pass  # 管道被关了:子进程已经停了
    finally:
        lines.put((name, None))


def _feed(process: subprocess.Popen, text: str) -> None:
    try:
        assert process.stdin is not None
        process.stdin.write(text.encode("utf-8"))
        process.stdin.close()
    except (BrokenPipeError, OSError):
        pass  # 它没读就退了 —— 退出码和输出会说为什么


def follow(
    args: Sequence[str],
    *,
    locale: str,
    timeout: float,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    on_line: Callable[[str, str], None] | None = None,
    stdin_text: str | None = None,
    tail: int = 300,
) -> Finished:
    """起一个子进程,读到它退出为止。每一行输出交给 `on_line(流名, 这一行)`(流名是 "out" / "err")。

    - 看到取消文件就停下它(连同子孙),抛 `Cancelled`;
    - 过了 `timeout` 秒同样停下,抛 `TimedOut` —— 由调用方说一句能照着做的话;
    - `on_line` 自己抛了异常也先停下子进程再往上抛:不留一个没人管的进程。
    """
    process = subprocess.Popen(
        list(args), cwd=cwd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        stdin=subprocess.PIPE if stdin_text is not None else subprocess.DEVNULL, **group_kwargs(),
    )
    lines: queue.Queue = queue.Queue()
    for stream, name in ((process.stdout, "out"), (process.stderr, "err")):
        threading.Thread(target=_pump, args=(stream, name, lines), daemon=True).start()
    if stdin_text is not None:
        # 另起一个线程写:内容比管道缓冲大、而对面又先顾着写输出时,在这里同步写会两边互相等死。
        threading.Thread(target=_feed, args=(process, stdin_text), daemon=True).start()
    kept: deque = deque(maxlen=tail)
    deadline = time.monotonic() + timeout
    open_streams = 2
    try:
        while open_streams:
            try:
                name, text = lines.get(timeout=0.25)
            except queue.Empty:
                name, text = "", ""
            if text is None:
                open_streams -= 1
            elif text:
                kept.append(text)
                if on_line is not None:
                    on_line(name, text)
            if cancel_requested():
                raise Cancelled(line(locale, "已取消。", "Cancelled."))
            if time.monotonic() > deadline:
                raise TimedOut(timeout)
    except BaseException:
        stop(process)
        raise
    process.wait()
    return Finished(returncode=process.returncode, tail=kept)


# ---------------------------------------------------------------- 跨进程的锁

@contextmanager
def exclusive(path: Path, *, locale: str, timeout: float) -> Iterator[None]:
    """同一时刻只有一个进程在做这件事(装环境、换工程)。等不到就抛 `TimedOut`;等的时候照样看取消。

    用操作系统的文件锁,不用「文件在不在」:进程被强杀时锁随之释放,不会留下一个永远锁着的标记。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")  # noqa: SIM115 —— 锁的生命期就是这个 with 块
    deadline = time.monotonic() + timeout
    try:
        while not _try_lock(handle):
            if cancel_requested():
                raise Cancelled(line(locale, "已取消。", "Cancelled."))
            if time.monotonic() > deadline:
                raise TimedOut(timeout)
            time.sleep(0.2)
        try:
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()


def _try_lock(handle) -> bool:
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(handle) -> None:
    try:
        if sys.platform == "win32":
            import msvcrt

            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
