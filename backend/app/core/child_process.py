"""Reading a child process without deadlocking on its own output.

The same mistake appeared independently in four places: hand the child stderr=PIPE, loop over
its stdout, and read stderr only once that loop ends. A child that writes more than one pipe
buffer (~64KB) to stderr blocks in write(2) while the parent blocks in read(2) on stdout, and
neither side ever moves again. It is easy to write and hard to notice, because it needs a
chatty child to trigger — ffmpeg on a damaged source emits a decode error per frame, a model
download writes tqdm progress bars, an agent sidecar logs.

Timeouts did not save any of them either: each passed one to process.wait(), which sits after
the loop and so is never reached. A deadline only has teeth if something kills the child, which
closes stdout and lets the loop finish.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from collections import deque
from collections.abc import Iterator, Sequence

from app.core.text import strip_ansi

logger = logging.getLogger(__name__)


class ChildProcess:
    """Iterate a child's stdout while its stderr drains and a deadline is enforced.

    Usage:
        child = ChildProcess(popen, timeout=600)
        for line in child.lines():
            ...
        stderr_tail = child.finish()
        if child.timed_out:
            ...
    """

    def __init__(
        self,
        process: subprocess.Popen,
        timeout: float | None = None,
        *,
        stderr_lines: int = 200,
    ) -> None:
        self._process = process
        self.timed_out = False
        # True once kill() ran — lets callers tell "we stopped it" (cancel/timeout) from
        # "the child died on its own", e.g. to decide whether an encoder fallback should retry.
        self.killed = False
        # Bounded: a chatty child must not be able to grow this without limit either.
        self._stderr: deque[str] = deque(maxlen=stderr_lines)
        self._drain = threading.Thread(target=self._read_stderr, daemon=True)
        self._drain.start()
        self._killer: threading.Timer | None = None
        if timeout is not None:
            self._killer = threading.Timer(timeout, self._kill)
            self._killer.daemon = True
            self._killer.start()

    def _read_stderr(self) -> None:
        """一直把 stderr 读空。

        **这个线程死了,这个类就退回它当初要解决的那个死锁**(见文件开头):没人读,管道写满,
        子进程卡在 write 上,而父进程卡在读 stdout 上。

        子进程往 stderr 写什么不由我们决定 —— ffmpeg 在坏源上逐帧报错、pip 打进度条、
        torch 打警告,其中任何一段非法字节都会让 `for line in ...` 抛 UnicodeDecodeError。
        所以这里**排空比读懂重要**:解码不了就丢弃原始字节继续读。
        """
        if self._process.stderr is None:
            return
        try:
            for line in self._process.stderr:
                self._stderr.append(line)
        except Exception:  # noqa: BLE001 — 读不懂也得读完
            try:
                self._process.stderr.detach().read()  # 只丢弃,不解码
            except Exception:  # noqa: BLE001
                pass  # 管道已经关了:子进程结束了,没什么可堵的了

    def _kill(self) -> None:
        self.timed_out = True
        self.kill()

    def kill(self) -> None:
        """Stop the child now. Safe to call from another thread, and more than once."""
        self.killed = True
        try:
            self._process.kill()
        except Exception:  # noqa: BLE001 — already gone
            pass

    def lines(self) -> Iterator[str]:
        """Yield stripped, non-empty stdout lines."""
        if self._process.stdout is None:
            return
        for line in self._process.stdout:
            line = line.strip()
            if line:
                yield line

    def raw_lines(self) -> Iterator[str]:
        """Yield stdout lines verbatim, for callers that parse prefixes or trailing newlines."""
        if self._process.stdout is None:
            return
        yield from self._process.stdout

    def stderr_tail(self, limit: int = 2000) -> str:
        # 同样会被端到界面上(下载失败那句话就来自这里)。
        return strip_ansi("".join(self._stderr))[-limit:]

    def finish(self, limit: int = 2000) -> str:
        """Stop the watchdog, reap the child, and return the tail of its stderr."""
        if self._killer is not None:
            self._killer.cancel()
        self._process.wait()
        self._drain.join(timeout=1.0)
        return self.stderr_tail(limit)


# ---------------------------------------------------------------------------
# 带日志的 subprocess.run
# ---------------------------------------------------------------------------
_SECRET_FLAGS = ("--api-key", "--token", "--password", "-p")
#: `scheme://user:secret@host` 里的那截 —— pip 镜像和 git 远端最常见的形状。
_URL_CREDENTIALS = re.compile(r"(?<=://)[^/\s:@]+:[^/\s@]+(?=@)")
#: 一眼能认出的密钥前缀。不求全,只求别把最常见的几种原样写进日志。
_TOKEN_LIKE = re.compile(r"\b(sk|pk|ghp|gho|hf|xox[baprs])[-_][A-Za-z0-9_\-]{8,}")


def _redact(arg: str) -> str:
    arg = _URL_CREDENTIALS.sub("***", arg)
    return _TOKEN_LIKE.sub(lambda m: f"{m.group(1)}-***", arg)


def _describe(args: Sequence[str] | str, limit: int = 240) -> str:
    """给人看的命令行。**脱敏之后**再截断 —— 反过来会把半个密钥留在日志里。"""
    parts = [args] if isinstance(args, str) else [str(part) for part in args]
    redacted: list[str] = []
    skip_next = False
    for part in parts:
        if skip_next:
            redacted.append("***")
            skip_next = False
            continue
        if part in _SECRET_FLAGS:
            skip_next = True
        redacted.append(_redact(part))
    line = " ".join(redacted)
    return line if len(line) <= limit else f"{line[:limit]}…"


def _took(seconds: float) -> str:
    return f"{seconds * 1000:.0f}ms" if seconds < 1 else f"{seconds:.1f}s"


def _plain(result: subprocess.CompletedProcess) -> subprocess.CompletedProcess:
    """把 text 模式下捕获到的输出去掉终端转义序列。bytes 原样留着 —— 那是调用方要的原始数据。"""
    for field in ("stdout", "stderr"):
        value = getattr(result, field, None)
        if isinstance(value, str):
            setattr(result, field, strip_ansi(value))
    return result


def run_logged(args, *, what: str, level: int = logging.INFO, **kwargs) -> subprocess.CompletedProcess:
    """`subprocess.run`,外加一行日志。**外部命令只从这一个口子出去。**

    此前 35 个调用点各自裸调 `subprocess.run`,于是 ffmpeg、转写 worker、pip、git 全是黑箱:
    失败时错误文本被塞进异常消息端到界面上,而"跑的是什么命令、跑了多久"没有任何地方留下。
    这一轮好几个 bug 都是先靠手动重跑命令才看见的。

    成功记 INFO(命令 + 耗时),失败记 WARNING 并带 stderr 尾巴 —— 失败时唯一有用的东西
    就是子进程自己说的那句话。超时单独记一条:它最容易被当成"卡住了"。

    `what` 是这条命令在业务上叫什么(「音频提取」「安装运行依赖」),因为 argv 的第一个词
    往往是一个解释器路径,看不出在干嘛。

    `level` 只影响**成功**那条:每导入一个素材就跑一次的 ffprobe、每次都问一遍的 docker 探测
    压到 DEBUG,否则真正值得看的那几行会被淹掉。失败一律 WARNING —— 频繁不是不报的理由。
    """
    line = _describe(args)
    started = time.monotonic()
    try:
        result = subprocess.run(args, **kwargs)
    except subprocess.TimeoutExpired:
        logger.warning("%s 超时(%s):%s", what, _took(time.monotonic() - started), line)
        raise
    except OSError as exc:
        logger.warning("%s 起不来:%s(%s)", what, exc, line)
        raise
    # 子进程默认当自己在终端里,输出带 ANSI 颜色码;而这些文字的去处常常是浏览器
    # (任务的 error 字段、下载失败提示)。在**唯一的出口**上去掉一次,好过在十来个
    # `raise XxxError(f"…{result.stderr}")` 里各记得一次。
    result = _plain(result)
    took = _took(time.monotonic() - started)
    if result.returncode == 0:
        logger.log(level, "%s 完成(%s):%s", what, took, line)
    else:
        stderr = result.stderr or ""
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", "replace")
        logger.warning(
            "%s 失败(退出码 %s,%s):%s\n%s", what, result.returncode, took, line, stderr.strip()[-800:]
        )
    return result
