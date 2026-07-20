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

import subprocess
import threading
from collections import deque
from collections.abc import Iterator


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
        if self._process.stderr is None:
            return
        for line in self._process.stderr:
            self._stderr.append(line)

    def _kill(self) -> None:
        self.timed_out = True
        self.kill()

    def kill(self) -> None:
        """Stop the child now. Safe to call from another thread, and more than once."""
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
        return "".join(self._stderr)[-limit:]

    def finish(self, limit: int = 2000) -> str:
        """Stop the watchdog, reap the child, and return the tail of its stderr."""
        if self._killer is not None:
            self._killer.cancel()
        self._process.wait()
        self._drain.join(timeout=1.0)
        return self.stderr_tail(limit)
