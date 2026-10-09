"""一个本机服务的日志:子进程直接写进 `logs/service-<连接>.log`,宿主从这个文件读进一份环形缓冲(最近 2000 行)。

**为什么子进程写文件、不写管道**:它要能活过后端(见 core/child_process.spawn_to_file)。后端被强杀之后管道没了,
子进程下一次写日志就是 EPIPE;写文件不受影响,后端重新起来、把它接回来以后,接着读同一个文件。

**读是拉的,没有专门的线程**:看日志、看状态的请求来时读一次新增的字节,看护线程每秒也读一次(见 supervisor)——
缓冲里的东西不会因为没人看就跟不上,文件也不会因为没人看就长到没边。

**滚动**:每次从头起(不是崩溃后的自动重启)之前,`service-<连接>.log` 依次挪成 `.1` `.2` `.3`;一直开着、超过
MAX_BYTES 时,把当前内容抄进 `.1` 再截断(子进程是追加写,截断以后接着从头写)—— 抄和截之间写进来的几行会丢,
换来的是不必让子进程重开文件。

**进度条**:tqdm 一类用回车(`\\r`)在同一行上刷新。缓冲照终端的样子收:回车之后的字盖掉这一行,而不是每刷一次
多一行,否则一次生成的进度条就把两千行挤满了。
"""

from __future__ import annotations

import logging
import os
import shutil
import threading

logger = logging.getLogger(__name__)
from collections import deque
from pathlib import Path
from typing import BinaryIO

from app.core.text import strip_ansi

#: 缓冲里留最近多少行(ADR 0041 §2)。
RING_LINES = 2000
#: 一直开着时,日志文件长到多大就滚一次。
MAX_BYTES = 10 * 1024 * 1024
#: 留几份滚下来的旧日志。
BACKUPS = 3
#: 接回上一个后端起的进程时,先从文件末尾读这么多进缓冲(那之前的在文件里,缓冲不必从头读)。
ADOPT_BACKLOG_BYTES = 256 * 1024
#: 一行最多留多少字;更长的截断(一个不换行、一直打字的子进程不该把一行攒成几 MB)。
MAX_LINE_CHARS = 4000


class ServiceLog:
    """一份日志文件 + 读到哪了 + 环形缓冲。线程安全:看护线程和请求线程都会读它。"""

    def __init__(self, path: Path, *, ring_lines: int = RING_LINES) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._ring: deque[str] = deque(maxlen=ring_lines)
        #: 回车之后还没换行的那一截:它是缓冲的最后一行,下一段字会盖掉它。
        self._open_line: str | None = None
        self._carriage = False
        self._offset = 0
        self._pending = b""

    # ---- 给子进程的那一头 ----

    def open_for_child(self, *, fresh: bool) -> BinaryIO:
        """给子进程写的文件(追加)。`fresh`:这是一次从头起 —— 先滚一次,缓冲清空;崩溃后的重启接着写同一个文件。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if fresh:
                self._rotate()
                self._ring.clear()
                self._open_line, self._carriage, self._pending = None, False, b""
                self._offset = 0
            else:
                self._offset = self._size()
        return open(self.path, "ab")  # noqa: SIM115 — 交给子进程,由调用方在 Popen 之后关掉自己这一份

    def follow_existing(self) -> None:
        """接回上一个后端起的进程:不滚、不清,从文件末尾往前一段读起。"""
        with self._lock:
            self._offset = max(0, self._size() - ADOPT_BACKLOG_BYTES)
            self._pending = b""
            self._pump_locked(skip_partial_first_line=self._offset > 0)

    # ---- 读的那一头 ----

    def pump(self) -> None:
        """把文件里新增的字节读进缓冲;文件太大了就滚一次。"""
        with self._lock:
            self._pump_locked()
            if self._size() > MAX_BYTES:
                self._copy_truncate()

    def tail(self, limit: int = RING_LINES) -> list[str]:
        """最近 `limit` 行(先把新增的读进来)。"""
        self.pump()
        with self._lock:
            lines = list(self._ring)
        return lines[-limit:] if limit > 0 else []

    # ---- 内部 ----

    def _size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def _pump_locked(self, *, skip_partial_first_line: bool = False) -> None:
        size = self._size()
        if size < self._offset:  # 被截断过(别处,或我们自己滚过):从头读
            self._offset, self._pending = 0, b""
        if size == self._offset:
            return
        try:
            with open(self.path, "rb") as handle:
                handle.seek(self._offset)
                data = handle.read(size - self._offset)
        except OSError:
            return
        self._offset += len(data)
        data = self._pending + data
        if skip_partial_first_line:
            cut = data.find(b"\n")
            data = data[cut + 1:] if cut >= 0 else b""
        # 末尾不完整的 UTF-8 字节留到下一次(一个汉字可能正好被切在两次读之间)
        keep = _incomplete_utf8_tail(data)
        self._pending = data[len(data) - keep:] if keep else b""
        self._feed(data[: len(data) - keep].decode("utf-8", "replace"))

    def _feed(self, text: str) -> None:
        for piece in _split_keeping_breaks(strip_ansi(text)):
            if piece == "\n":
                if self._open_line is not None:
                    self._open_line = None
                elif not self._carriage:
                    self._ring.append("")
                self._carriage = False
                continue
            if piece == "\r":
                self._carriage = True
                continue
            piece = piece[:MAX_LINE_CHARS]
            if self._open_line is not None and self._carriage:
                self._open_line = piece  # 回车之后:盖掉这一行
                self._ring[-1] = piece
            elif self._open_line is not None:
                self._open_line = (self._open_line + piece)[:MAX_LINE_CHARS]
                self._ring[-1] = self._open_line
            else:
                self._open_line = piece
                self._ring.append(piece)
            self._carriage = False

    def _rotate(self) -> None:
        if not self.path.exists() or self._size() == 0:
            return
        try:
            for index in range(BACKUPS, 0, -1):
                older = self.path.with_name(f"{self.path.name}.{index}")
                newer = self.path.with_name(f"{self.path.name}.{index - 1}") if index > 1 else self.path
                if newer.exists():
                    os.replace(newer, older)
        except OSError as exc:
            #: 轮转失败 = 这个服务的日志从此无限增长(兄弟函数 _rotate 有注释,这条补留痕)。
            logger.debug("服务日志 %s 轮转失败: %s(日志会继续往大长)", self.path, exc)  # 滚不动(Windows 上别的进程还开着它)就接着往同一个文件里写

    def _copy_truncate(self) -> None:
        try:
            for index in range(BACKUPS, 1, -1):
                older = self.path.with_name(f"{self.path.name}.{index}")
                newer = self.path.with_name(f"{self.path.name}.{index - 1}")
                if newer.exists():
                    os.replace(newer, older)
            shutil.copyfile(self.path, self.path.with_name(f"{self.path.name}.1"))
            with open(self.path, "r+b") as handle:
                handle.truncate(0)
            self._offset, self._pending = 0, b""
        except OSError as exc:
            #: 轮转失败 = 这个服务的日志从此无限增长(兄弟函数 _rotate 有注释,这条补留痕)。
            logger.debug("服务日志 %s 轮转失败: %s(日志会继续往大长)", self.path, exc)


def _split_keeping_breaks(text: str) -> list[str]:
    """按 `\\n` 和 `\\r` 切开,切口本身也留在结果里(`\\r\\n` 当作一个换行)。"""
    out: list[str] = []
    start = 0
    index = 0
    while index < len(text):
        char = text[index]
        if char in "\r\n":
            if index > start:
                out.append(text[start:index])
            if char == "\r" and index + 1 < len(text) and text[index + 1] == "\n":
                out.append("\n")
                index += 2
            else:
                out.append(char)
                index += 1
            start = index
            continue
        index += 1
    if start < len(text):
        out.append(text[start:])
    return out


def _incomplete_utf8_tail(data: bytes) -> int:
    """末尾那个没写完的 UTF-8 字符有几个字节(0 = 完整)。"""
    for back in range(1, min(4, len(data)) + 1):
        byte = data[-back]
        if byte & 0b1100_0000 == 0b1000_0000:  # 续字节,接着往前找首字节
            continue
        if byte & 0b1000_0000 == 0:
            return 0
        need = 2 if byte & 0b1110_0000 == 0b1100_0000 else 3 if byte & 0b1111_0000 == 0b1110_0000 else 4
        return back if back < need else 0
    return 0


__all__ = ["BACKUPS", "MAX_BYTES", "RING_LINES", "ServiceLog"]
