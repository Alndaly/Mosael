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
import os
import re
import signal
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Callable, Iterator, Sequence
from typing import Any

from app.core.text import strip_ansi

logger = logging.getLogger(__name__)

#: 文本模式的子进程一律 UTF-8。
#:
#: **不给 `encoding` 就是问平台要**:mac/Linux 上恰好是 UTF-8,中文 Windows 上是 GBK。而这个
#: 仓库的子进程 —— Node sidecar、Python worker、ffmpeg、pip、git —— 都按 UTF-8 说话。用户在
#: Windows 上和智能体说的第一句中文就是这么炸的:
#:
#:     'gbk' codec can't decode byte 0x88 in position 52: illegal multibyte sequence
#:
#: `errors="replace"`:这条通道上同时走**日志**(pip / git 在中文 Windows 上真的会吐 GBK 字节)。
#: 为一行读不懂的日志把整轮对话炸掉,是比几个问号更坏的结果 —— 而协议行是我们自己的 worker 发的,
#: 它们本来就是 UTF-8,替换不会落在上面。
TEXT_IO: dict[str, str] = {"encoding": "utf-8", "errors": "replace"}

#: `finish()` 等子进程自己退出的上限,超过就杀。
#:
#: 和构造函数那个 `timeout` 是**两件事**:那个是「这一轮跑太久」,这个是「stdout 都读完了、
#: stdin 都关了,它还不退」。后者在本仓库有真实成因 —— Node 的 sidecar 里挂着没人管的后台
#: promise,事件循环不空就不退。20 秒:到这一步该产出的都产出了,再等只是在赌。
REAP_TIMEOUT = 20.0


# ---------------------------------------------------------------------------
# 自成一组的子进程:停它就是停它起的所有进程
# ---------------------------------------------------------------------------


def own_group() -> dict[str, Any]:
    """让子进程**自成一组**的 Popen 参数。配 `kill_tree` 用。

    `Popen.kill()` 只杀那一个 pid。子进程要是又起了孙进程(插件入口起 `node render.mjs`、manim 起
    ffmpeg),孙进程照跑,而且攥着继承来的 stdout —— 读输出的那一侧等不到 EOF,「杀掉了」并没有让
    调用返回。自成一组之后,一次 `kill_tree` 停下整组。
    """
    if sys.platform == "win32":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_tree(process: subprocess.Popen) -> None:
    """停下 `process` 和它起的所有进程(它得是按 `own_group()` 起的)。可以重复调,可以跨线程调。

    POSIX:新会话里 pgid 就是它的 pid,`killpg` 一次停下整组 —— 入口进程已经自己退了、只剩孙进程
    攥着管道时也一样。Windows:`taskkill /T` 按父子关系往下找。
    """
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True, timeout=10, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass  # 整组都已经退了
    try:
        process.kill()
    except Exception:  # noqa: BLE001 — already gone
        pass


def popen_text(args, **kwargs) -> subprocess.Popen:
    """按行说话的子进程**只从这一个口子起**。

    `subprocess.run` 那条路早就收进了 `run_logged`,而常驻/流式的那些一直在各自裸调 `Popen` ——
    于是"文本模式用什么编码"这件事有二十来份答案,每一份都是"问平台要"。
    """
    # 显式要 bytes 的照办,别硬塞一个 encoding 把它偷偷变回文本
    # (subprocess 里只要给了 encoding 就是文本模式,`text=False` 拦不住)。
    if kwargs.get("text") is False or kwargs.get("universal_newlines") is False:
        return subprocess.Popen(args, **kwargs)
    kwargs.setdefault("text", True)
    for key, value in TEXT_IO.items():
        kwargs.setdefault(key, value)
    return subprocess.Popen(args, **kwargs)


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
        own_group: bool = False,
    ) -> None:
        self._process = process
        #: 进程是按 `own_group()` 起的:停它就停整组(见 kill_tree)。
        self._own_group = own_group
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
        if self._own_group:
            kill_tree(self._process)
            return
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

    def finish(self, limit: int = 2000, *, reap_timeout: float = REAP_TIMEOUT) -> str:
        """Reap the child, **then** stop the watchdog, and return the tail of its stderr.

        **这两步的顺序就是这个方法的全部要点。** 原先是先 `cancel()` 再无限期 `wait()` ——
        也就是这个类在它唯一的收尾出口上,做的第一件事是拔掉文件开头那句话说的那颗牙
        (「A deadline only has teeth if something kills the child」)。子进程只要不自己退,
        `wait()` 就永远不返回,而此时已经没有任何东西能打断它。

        现场:pi sidecar 那一轮被用户按「停止」结束,stdin 关了,`main()` 返回了,但 Node 要等
        事件循环空了才退,而后台子智能体还挂着在飞的 HTTP 请求。于是 `wait()` 不返回 →
        调用方 `finally` 里「把会话拨回 idle」那段永远执行不到 → **界面上那个会话永远停在
        「思考中」**,之后每条消息都被拒绝(见 test_sidecar_backpressure 开头记的同一个症状:
        那次是 stderr 管道死锁,这次是另一条通往同一个症状的路)。

        所以收尾自己也要有时限,而且是**独立的第二个数**:看门狗管的是「这一轮跑太久」,
        `reap_timeout` 管的是「stdout 都读完了它还不退」。两件事,两个数。看门狗留到 `wait()`
        真的返回之后再撤 —— 它在这期间开火是**对的**,那正是它存在的理由。
        """
        try:
            self._process.wait(timeout=reap_timeout)
        except subprocess.TimeoutExpired:
            logger.warning(
                "子进程 pid=%s 在 stdout 读完后 %.0f 秒仍未退出,强制结束", self._process.pid, reap_timeout
            )
            # 不置 timed_out:这一轮**已经出了结果**,只是子进程赖着不走。把它说成超时会让
            # 调用方把一次成功的回合报成「运行超过 N 秒未返回」。
            self.kill()
            self._process.wait()
        finally:
            if self._killer is not None:
                self._killer.cancel()
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


def _run_announcing_child(
    args,
    on_child: Callable[[subprocess.Popen], Any] | None,
    *,
    input=None,
    capture_output: bool = False,
    timeout: float | None = None,
    check: bool = False,
    group: bool = False,
    **kwargs,
) -> subprocess.CompletedProcess:
    """`subprocess.run` 的同一套语义,多两样:子进程一起来就交给 `on_child`;`group` 时自成一组。

    `subprocess.run` 不交出 Popen,而任务要在取消时杀得掉它(见 jobs.register_job_child),
    所以照 CPython 的实现写这一份 —— 要登记子进程、或要超时时停下整棵进程树的调用方走这里。
    """
    if input is not None:
        kwargs["stdin"] = subprocess.PIPE
    if capture_output:
        kwargs["stdout"] = kwargs["stderr"] = subprocess.PIPE
    if group:
        kwargs.update(own_group())

    def stop(process: subprocess.Popen) -> None:
        if group:
            kill_tree(process)
        else:
            process.kill()

    with subprocess.Popen(args, **kwargs) as process:
        try:
            if on_child is not None:
                on_child(process)
            stdout, stderr = process.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            stop(process)
            process.wait()
            raise
        except BaseException:
            stop(process)
            raise
        retcode = process.poll()
    if check and retcode:
        raise subprocess.CalledProcessError(retcode, process.args, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(process.args, retcode, stdout, stderr)


def run_logged(
    args,
    *,
    what: str,
    level: int = logging.INFO,
    on_child: Callable[[subprocess.Popen], Any] | None = None,
    group: bool = False,
    **kwargs,
) -> subprocess.CompletedProcess:
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

    `on_child` 在子进程起来的那一刻拿到它的 Popen —— 给要在任务取消时杀掉它的调用方
    (插件工具,见 plugins/runtime.execute_tool)。

    `group=True`:子进程自成一组,超时停下的是整棵进程树(见 own_group / kill_tree)——
    跑别人的代码时要这样,它起的孙进程不归我们管,却会在超时之后照跑。
    """
    # 文本模式默认 UTF-8(见 TEXT_IO)。调用方只说了「我要字符串」,没说"按这台机器的
    # locale 猜一个编码" —— 而后者在中文 Windows 上是 GBK,ffprobe 报一个中文文件名就炸。
    if kwargs.get("text") or kwargs.get("universal_newlines"):
        for key, value in TEXT_IO.items():
            kwargs.setdefault(key, value)
    line = _describe(args)
    started = time.monotonic()
    try:
        if on_child is None and not group:
            result = subprocess.run(args, **kwargs)
        else:
            result = _run_announcing_child(args, on_child, group=group, **kwargs)
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


class ProcessOutputLimitExceeded(RuntimeError):
    """A child exceeded its combined stdout/stderr byte budget."""


def run_bounded(args, *, input: bytes = b"", timeout: float, max_output_bytes: int,
                env: dict[str, str] | None = None, cwd: str | None = None, what: str) -> subprocess.CompletedProcess:
    """Binary pipes with a deadline covering stdin and bounded, concurrent output collection.

    A line iterator or communicate() would buffer an arbitrarily long line/output before
    enforcing the budget. Keep at most the combined budget and stop on the first excess byte.
    """
    started = time.monotonic()
    process = popen_text(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         text=False, env=env, cwd=cwd)
    output, errors = bytearray(), bytearray()
    exceeded = threading.Event()
    lock = threading.Lock()
    total = 0

    def drain(stream, target):
        nonlocal total
        try:
            while chunk := stream.read1(16 * 1024):
                with lock:
                    remaining = max(0, max_output_bytes - total)
                    target.extend(chunk[:remaining])
                    total += len(chunk)
                    if total > max_output_bytes:
                        exceeded.set()
                if exceeded.is_set():
                    process.kill()
                    break
        finally:
            stream.close()

    def feed():
        try:
            process.stdin.write(input)
            process.stdin.flush()
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    threads = [threading.Thread(target=drain, args=(process.stdout, output), daemon=True),
               threading.Thread(target=drain, args=(process.stderr, errors), daemon=True),
               threading.Thread(target=feed, daemon=True)]
    for thread in threads:
        thread.start()
    try:
        process.wait(timeout=max(0.001, timeout - (time.monotonic() - started)))
    except BaseException:
        process.kill()
        process.wait()
        raise
    finally:
        for thread in threads:
            thread.join(timeout=1)
        logger.debug("%s finished (%s): %s", what, _took(time.monotonic() - started), _describe(args))
    if exceeded.is_set():
        raise ProcessOutputLimitExceeded(f"output exceeded {max_output_bytes} bytes")
    return subprocess.CompletedProcess(args, process.returncode, bytes(output), bytes(errors))
