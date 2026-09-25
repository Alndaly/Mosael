"""一轮图的「停」信号 —— 引擎立它,节点里的等待认它。

单独成一个模块,是因为两边都要用它而彼此不该互相 import:引擎(engine)在节点失败、工作流
被取消的那一刻立起来;执行器共用的等待(executors.common.wait_until)每一拍看一眼。
"""

from __future__ import annotations

import contextvars
import threading
from collections.abc import Iterator
from contextlib import contextmanager

#: 这一轮图的「停」信号,外层图在前、当前这张图在最后。
#:
#: 一轮图要停有两种原因:外层工作流被取消(库里那一行落了终态),或者**同一张图里有节点失败了**
#: —— 整条工作流已经失败,还在跑的兄弟节点做完了也没人要。前者任何人都能从库里读到;后者只有
#: 引擎知道,由它在失败那一刻立起来(见 engine.execute_graph)。
#:
#: 用上下文变量传:节点在引擎的线程池里带着提交时的上下文跑(copy_context),嵌套的图(循环体、
#: 子图)在节点线程里再压一层 —— 外层停了,里面所有层都看得见。
_HALTS: contextvars.ContextVar[tuple[threading.Event, ...]] = contextvars.ContextVar(
    "mosael_workflow_halts", default=()
)


@contextmanager
def halt_scope() -> Iterator[threading.Event]:
    """为一轮图压一个「停」信号。在这里面提交的节点都认它。"""
    halt = threading.Event()
    token = _HALTS.set((*_HALTS.get(), halt))
    try:
        yield halt
    finally:
        _HALTS.reset(token)


def halted() -> bool:
    """当前这一轮(或它外面任何一层)有没有立起停的信号。"""
    return any(halt.is_set() for halt in _HALTS.get())
